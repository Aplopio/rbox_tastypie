import datetime
from dateutil.parser import parse
from decimal import Decimal
import re
from django import forms
from django.utils.functional import memoize

from django.core.exceptions import ObjectDoesNotExist, MultipleObjectsReturned
from django import forms as djangoform
from django.utils import datetime_safe, importlib
from django.core.urlresolvers import resolve
from tastypie.bundle import Bundle
from tastypie.exceptions import ApiFieldError, NotFound, HydrationError
from tastypie.utils import dict_strip_unicode_keys, make_aware, LimitedSizeDict


class NOT_PROVIDED:
    def __str__(self):
        return 'No default provided.'


DATE_REGEX = re.compile('^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2}).*?$')
DATETIME_REGEX = re.compile('^(?P<year>\d{4})-(?P<month>\d{2})-(?P<day>\d{2})(T|\s+)(?P<hour>\d{2}):(?P<minute>\d{2}):(?P<second>\d{2}).*?$')


class AllowEverythingMultipleChoiceField(forms.MultipleChoiceField):
    def clean(self, value):
        if type(value) ==list:
            for validator in self.validators:
                validator(value)
            return value
        elif not self.required and value==None:
            return value
        else:
            raise forms.ValidationError("Expects a list,'%s' given." % type(value))

class AllowEverythingChoiceField(forms.ChoiceField):
    def clean(self, value):
        return value

# All the ApiField variants.

class ApiField(object):
    """The base implementation of a field used by the resources."""
    dehydrated_type = 'string'
    help_text = ''

    def __init__(self, attribute=None, default=NOT_PROVIDED, null=False, blank=False, readonly=False,
            unique=False, help_text=None, use_in='all', change_handler=None):
        """
        Sets up the field. This is generally called when the containing
        ``Resource`` is initialized.

        Optionally accepts an ``attribute``, which should be a string of
        either an instance attribute or callable off the object during the
        ``dehydrate`` or push data onto an object during the ``hydrate``.
        Defaults to ``None``, meaning data will be manually accessed.

        Optionally accepts a ``default``, which provides default data when the
        object being ``dehydrated``/``hydrated`` has no data on the field.
        Defaults to ``NOT_PROVIDED``.

        Optionally accepts a ``null``, which indicated whether or not a
        ``None`` is allowable data on the field. Defaults to ``False``.

        Optionally accepts a ``blank``, which indicated whether or not
        data may be omitted on the field. Defaults to ``False``.

        Optionally accepts a ``readonly``, which indicates whether the field
        is used during the ``hydrate`` or not. Defaults to ``False``.

        Optionally accepts a ``unique``, which indicates if the field is a
        unique identifier for the object.

        Optionally accepts ``help_text``, which lets you provide a
        human-readable description of the field exposed at the schema level.
        Defaults to the per-Field definition.

        Optionally accepts ``use_in``. This may be one of ``list``, ``detail``
        ``all`` or a callable which accepts a ``bundle`` and returns
        ``True`` or ``False``. Indicates wheather this field will be included
        during dehydration of a list of objects or a single object. If ``use_in``
        is a callable, and returns ``True``, the field will be included during
        dehydration.
        Defaults to ``all``.
        """
        # Track what the index thinks this field is called.
        self.instance_name = None
        self._resource = None
        self.attribute = attribute
        self._default = default
        self.null = null
        self.blank = blank
        self.readonly = readonly
        self.value = None
        self.unique = unique
        self.use_in = 'all'
        self.change_handler = change_handler

        if use_in in ['all', 'detail', 'list'] or callable(use_in):
            self.use_in = use_in

        if help_text:
            self.help_text = help_text

    def build_schema(self, **kwargs):
        field_schema = {
            'default': self.default,
            'type': self.dehydrated_type,
            'nullable': self.null,
            'blank': self.blank,
            'readonly': self.readonly,
            'help_text': self.help_text,
            'unique': self.unique,
            }
        return field_schema


    @property
    def formfield(self):
        return djangoform.CharField

    def contribute_to_class(self, cls, name):
        # Do the least we can here so that we don't hate ourselves in the
        # morning.
        self.instance_name = name
        self._resource = cls

    def has_default(self):
        """Returns a boolean of whether this field has a default value."""
        return self._default is not NOT_PROVIDED

    @property
    def default(self):
        """Returns the default value for the field."""
        if callable(self._default):
            return self._default()

        return self._default

    def dehydrate(self, bundle):
        """
        Takes data from the provided object and prepares it for the
        resource.
        """
        if self.attribute is not None:
            # Check for `__` in the field for looking through the relation.
            attrs = self.attribute.split('__')
            current_object = bundle.obj

            for attr in attrs:
                previous_object = current_object
                current_object = getattr(current_object, attr, None)

                if current_object is None:
                    if self.has_default():
                        current_object = self._default
                        # Fall out of the loop, given any further attempts at
                        # accesses will fail miserably.
                        break
                    elif self.null:
                        current_object = None
                        # Fall out of the loop, given any further attempts at
                        # accesses will fail miserably.
                        break
                    else:
                        raise ApiFieldError("The object '%r' has an empty attribute '%s' and doesn't allow a default or null value." % (previous_object, attr))

            if callable(current_object):
                current_object = current_object()

            return self.convert(current_object)

        if self.has_default():
            return self.convert(self.default)
        else:
            return None

    def convert(self, value):
        """
        Handles conversion between the data found and the type of the field.

        Extending classes should override this method and provide correct
        data coercion.
        """
        return value

    def hydrate(self, bundle):
        """
        Takes data stored in the bundle for the field and returns it. Used for
        taking simple data and building a instance object.
        """
        if self.readonly:
            return None
        if not bundle.data.has_key(self.instance_name):
            if getattr(self, 'is_related', False) and not getattr(self, 'is_m2m', False):
                # We've got an FK (or alike field) & a possible parent object.
                # Check for it.
                if bundle.related_obj and bundle.related_name in (self.attribute, self.instance_name):
                    return bundle.related_obj
            if self.blank:
                return None
            elif self.attribute and getattr(bundle.obj, self.attribute, None):
                return getattr(bundle.obj, self.attribute)
            elif self.instance_name and hasattr(bundle.obj, self.instance_name):
                return getattr(bundle.obj, self.instance_name)
            elif self.has_default():
                if callable(self._default):
                    return self._default()

                return self._default
            elif self.null:
                return None
            else:
                raise ApiFieldError("The '%s' field has no data and doesn't allow a default or null value." % self.instance_name)

        return bundle.data[self.instance_name]


class CharField(ApiField):
    """
    A text field of arbitrary length.

    Covers both ``models.CharField`` and ``models.TextField``.
    """
    dehydrated_type = 'string'
    help_text = 'Unicode string data. Ex: "Hello World"'

    def convert(self, value):
        if value is None:
            return None

        return unicode(value)


class FileField(ApiField):
    """
    A file-related field.

    Covers both ``models.FileField`` and ``models.ImageField``.
    """
    dehydrated_type = 'string'
    help_text = 'A file URL as a string. Ex: "http://media.example.com/media/photos/my_photo.jpg"'

    @property
    def formfield(self):
        return djangoform.FileField

    def convert(self, value):
        if value is None:
            return None

        try:
            # Try to return the URL if it's a ``File``, falling back to the string
            # itself if it's been overridden or is a default.
            return getattr(value, 'url', value)
        except ValueError:
            return None


class IntegerField(ApiField):
    """
    An integer field.

    Covers ``models.IntegerField``, ``models.PositiveIntegerField``,
    ``models.PositiveSmallIntegerField`` and ``models.SmallIntegerField``.
    """
    dehydrated_type = 'integer'
    help_text = 'Integer data. Ex: 2673'

    @property
    def formfield(self):
        return djangoform.IntegerField

    def convert(self, value):
        if value is None:
            return None

        return int(value)


class FloatField(ApiField):
    """
    A floating point field.
    """
    dehydrated_type = 'float'
    help_text = 'Floating point numeric data. Ex: 26.73'

    @property
    def formfield(self):
        return djangoform.FloatField

    def convert(self, value):
        if value is None:
            return None

        return float(value)


class DecimalField(ApiField):
    """
    A decimal field.
    """
    dehydrated_type = 'decimal'
    help_text = 'Fixed precision numeric data. Ex: 26.73'

    @property
    def formfield(self):
        return djangoform.DecimalField

    def convert(self, value):
        if value is None:
            return None

        return Decimal(value)

    def hydrate(self, bundle):
        value = super(DecimalField, self).hydrate(bundle)

        if value and not isinstance(value, Decimal):
            value = Decimal(value)

        return value


class BooleanField(ApiField):
    """
    A boolean field.

    Covers both ``models.BooleanField`` and ``models.NullBooleanField``.
    """
    dehydrated_type = 'boolean'
    help_text = 'Boolean data. Ex: True'

    @property
    def formfield(self):
        return djangoform.BooleanField

    def convert(self, value):
        if value is None:
            return None

        return bool(value)


class ListField(ApiField):
    """
    A list field.
    """
    dehydrated_type = 'list'
    help_text = "A list of data. Ex: ['abc', 26.73, 8]"

    def convert(self, value):
        if value is None:
            return None

        return list(value)


class DictField(ApiField):
    """
    A dictionary field.
    """
    dehydrated_type = 'dict'
    help_text = "A dictionary of data. Ex: {'price': 26.73, 'name': 'Daniel'}"

    def convert(self, value):
        if value is None:
            return None

        return dict(value)


class DateField(ApiField):
    """
    A date field.
    """
    dehydrated_type = 'date'
    help_text = 'A date as a string. Ex: "2010-11-10"'

    @property
    def formfield(self):
        return djangoform.DateField

    def convert(self, value):
        if value is None:
            return None

        if isinstance(value, basestring):
            match = DATE_REGEX.search(value)

            if match:
                data = match.groupdict()
                return datetime_safe.date(int(data['year']), int(data['month']), int(data['day']))
            else:
                raise ApiFieldError("Date provided to '%s' field doesn't appear to be a valid date string: '%s'" % (self.instance_name, value))

        return value

    def hydrate(self, bundle):
        value = super(DateField, self).hydrate(bundle)

        if value and not hasattr(value, 'year'):
            try:
                # Try to rip a date/datetime out of it.
                value = make_aware(parse(value))

                if hasattr(value, 'hour'):
                    value = value.date()
            except ValueError:
                pass

        return value


class DateTimeField(ApiField):
    """
    A datetime field.
    """
    dehydrated_type = 'datetime'
    help_text = 'A date & time as a string. Ex: "2010-11-10T03:07:43"'

    @property
    def formfield(self):
        return djangoform.DateTimeField

    def convert(self, value):
        if value is None:
            return None

        if isinstance(value, basestring):
            match = DATETIME_REGEX.search(value)

            if match:
                data = match.groupdict()
                return make_aware(datetime_safe.datetime(int(data['year']), int(data['month']), int(data['day']), int(data['hour']), int(data['minute']), int(data['second'])))
            else:
                raise ApiFieldError("Datetime provided to '%s' field doesn't appear to be a valid datetime string: '%s'" % (self.instance_name, value))

        return value

    def hydrate(self, bundle):
        value = super(DateTimeField, self).hydrate(bundle)
        if value and not hasattr(value, 'year'):
            try:
                # Try to rip a date/datetime out of it.
                value = make_aware(parse(value))
            except ValueError:
                pass

        return value


class RelatedField(ApiField):
    """
    Provides access to data that is related within the database.

    The ``RelatedField`` base class is not intended for direct use but provides
    functionality that ``ToOneField`` and ``ToManyField`` build upon.

    The contents of this field actually point to another ``Resource``,
    rather than the related object. This allows the field to represent its data
    in different ways.

    The abstractions based around this are "leaky" in that, unlike the other
    fields provided by ``tastypie``, these fields don't handle arbitrary objects
    very well. The subclasses use Django's ORM layer to make things go, though
    there is no ORM-specific code at this level.
    """
    dehydrated_type = 'related'
    is_related = True
    self_referential = False
    help_text = 'A related resource. Can be either a URI or set of nested resource data.'

    @property
    def formfield(self):
        if getattr(self,'is_m2m',False):
            return AllowEverythingMultipleChoiceField
        else:
            return AllowEverythingChoiceField

    def __init__(self, to, attribute, related_name=None, default=NOT_PROVIDED, null=False, blank=False, readonly=False, full=False, unique=False, help_text=None, use_in='all', full_list=True, full_detail=True, change_handler=None):
        """
        Builds the field and prepares it to access to related data.

        The ``to`` argument should point to a ``Resource`` class, NOT
        to a ``Model``. Required.

        The ``attribute`` argument should specify what field/callable points to
        the related data on the instance object. Required.

        Optionally accepts a ``related_name`` argument. Currently unused, as
        unlike Django's ORM layer, reverse relations between ``Resource``
        classes are not automatically created. Defaults to ``None``.

        Optionally accepts a ``null``, which indicated whether or not a
        ``None`` is allowable data on the field. Defaults to ``False``.

        Optionally accepts a ``blank``, which indicated whether or not
        data may be omitted on the field. Defaults to ``False``.

        Optionally accepts a ``readonly``, which indicates whether the field
        is used during the ``hydrate`` or not. Defaults to ``False``.

        Optionally accepts a ``full``, which indicates how the related
        ``Resource`` will appear post-``dehydrate``. If ``False``, the
        related ``Resource`` will appear as a URL to the endpoint of that
        resource. If ``True``, the result of the sub-resource's
        ``dehydrate`` will be included in full.

        Optionally accepts a ``unique``, which indicates if the field is a
        unique identifier for the object.

        Optionally accepts ``help_text``, which lets you provide a
        human-readable description of the field exposed at the schema level.
        Defaults to the per-Field definition.

        Optionally accepts ``use_in``. This may be one of ``list``, ``detail``
        ``all`` or a callable which accepts a ``bundle`` and returns
        ``True`` or ``False``. Indicates wheather this field will be included
        during dehydration of a list of objects or a single object. If ``use_in``
        is a callable, and returns ``True``, the field will be included during
        dehydration.
        Defaults to ``all``.

        Optionally accepts a ``full_list``, which indicated whether or not
        data should be fully dehydrated when the request is for a list of
        resources. Accepts ``True``, ``False`` or a callable that accepts
        a bundle and returns ``True`` or ``False``. Depends on ``full``
        being ``True``. Defaults to ``True``.

        Optionally accepts a ``full_detail``, which indicated whether or not
        data should be fully dehydrated when then request is for a single
        resource. Accepts ``True``, ``False`` or a callable that accepts a
        bundle and returns ``True`` or ``False``.Depends on ``full``
        being ``True``. Defaults to ``True``.
        """
        self.instance_name = None
        self._resource = None
        self.to = to
        self.attribute = attribute
        self.related_name = related_name
        self._default = default
        self.null = null
        self.blank = blank
        self.readonly = readonly
        self.full = full
        self.api_name = None
        self.resource_name = None
        self.unique = unique
        self._to_class = None
        self.use_in = 'all'
        self.full_list = full_list
        self.full_detail = full_detail
        self.change_handler = change_handler

        if use_in in ['all', 'detail', 'list'] or callable(use_in):
            self.use_in = use_in

        if self.to == 'self':
            self.self_referential = True
            self._to_class = self.__class__

        if help_text:
            self.help_text = help_text

    def build_schema(self, **kwargs):
        field_schema = super(RelatedField, self).build_schema(**kwargs)
        return field_schema



        if not hasattr(self, "related_type"):
            raise ApiFieldError("All related fields must have attribute related_type")

        return

        if isinstance(field_object, fields.BaseSubResourceField):
            data['fields'][field_name]['schema'] ="%s%s/schema/"%(self.get_resource_uri(),field_name)
        else:
            related_resource = field_object.get_related_resource()
            data['fields'][field_name]['schema'] = unicode(related_resource.get_resource_uri())+ "schema/"  #unicode(.get_resource_uri()) + "schema/"

            if related_resource._meta.include_resource_uri==False or not field_object.to_class().get_resource_uri():
                data['fields'][field_name]['schema'] = field_object.to_class().build_schema()
                data['fields'][field_name]['type'] = "dict"
                del data['fields'][field_name]["related_type"]
        return data


    def contribute_to_class(self, cls, name):
        super(RelatedField, self).contribute_to_class(cls, name)

        # Check if we're self-referential and hook it up.
        # We can't do this quite like Django because there's no ``AppCache``
        # here (which I think we should avoid as long as possible).
        if self.self_referential or self.to == 'self':
            self._to_class = cls

    def get_related_resource(self, related_instance=None, bundle=None):
        """
        Instaniates the related resource.
        """
        related_resource = self.to_class()

        # Fix the ``api_name`` if it's not present.
        if related_resource._meta.api_name is None:
            if self._resource and not self._resource._meta.api_name is None:
                related_resource._meta.api_name = self._resource._meta.api_name

        # Try to be efficient about DB queries.
        related_resource.instance = related_instance
        return related_resource

    @property
    def to_class(self):
        # We need to be lazy here, because when the metaclass constructs the
        # Resources, other classes may not exist yet.
        # That said, memoize this so we never have to relookup/reimport.
        if self._to_class:
            return self._to_class

        if not isinstance(self.to, basestring):
            self._to_class = self.to
            return self._to_class

        # It's a string. Let's figure it out.
        if '.' in self.to:
            # Try to import.
            module_bits = self.to.split('.')
            module_path, class_name = '.'.join(module_bits[:-1]), module_bits[-1]
            module = importlib.import_module(module_path)
        else:
            # We've got a bare class name here, which won't work (No AppCache
            # to rely on). Try to throw a useful error.
            raise ImportError("Tastypie requires a Python-style path (<module.module.Class>) to lazy load related resources. Only given '%s'." % self.to)

        self._to_class = getattr(module, class_name, None)

        if self._to_class is None:
            raise ImportError("Module '%s' does not appear to have a class called '%s'." % (module_path, class_name))

        return self._to_class

    def dehydrate_related(self, bundle, related_resource):
        """
        Based on the ``full_resource``, returns either the endpoint or the data
        from ``full_dehydrate`` for the related resource.
        """
        should_dehydrate_full_resource = self.should_full_dehydrate(bundle)
        related_bundle = related_resource.build_bundle(
                obj=related_resource.instance,
                request=bundle.request,
                objects_saved=bundle.objects_saved
            )

        if not should_dehydrate_full_resource:
            # Be a good netizen.
            return related_resource.get_resource_uri(related_bundle)
        else:
            # ZOMG extra data and big payloads.
            return related_resource.full_dehydrate(related_bundle)

    def resource_from_uri(self, fk_resource, uri, request=None, related_obj=None, related_name=None):
        """
        Given a URI is provided, the related resource is attempted to be
        loaded based on the identifiers in the URI.
        """
        try:
            obj = fk_resource.get_via_uri(uri, request=request)
            bundle = fk_resource.build_bundle(
                obj=obj,
                request=request
            )
            return fk_resource.full_dehydrate(bundle)
        except ObjectDoesNotExist:
            raise ApiFieldError("Could not find the provided object via resource URI '%s'." % uri)


    def get_obj_from_data(self, resource, bundle, **kwargs):
        if not bundle.obj or not resource.get_bundle_detail_data(bundle):
            try:
                if 'resource_uri' in kwargs:
                    return resource.get_via_uri(kwargs['resource_uri'],request)
            except: pass
            try:
                if 'id' in kwargs:
                    return resource.obj_get(bundle,id=kwargs['id'])
            except: pass
            try:
                lookup_kwargs = resource.lookup_kwargs_with_identifiers(bundle, kwargs)
            except:
                # if there is trouble hydrating the data, fall back to just
                # using kwargs by itself (usually it only contains a "pk" key
                # and this will work fine.
                lookup_kwargs = kwargs

            try:
                obj = resource.obj_get(bundle=bundle, _optimize_query=False, **lookup_kwargs)
            except ObjectDoesNotExist:
                raise NotFound("A model instance matching the provided arguments could not be found.")
            return obj


    def resource_from_data(self, fk_resource, data, request=None, related_obj=None, related_name=None):
        """
        Given a dictionary-like structure is provided, a fresh related
        resource is created using that data.
        """
        # Try to hydrate the data provided.
        data = dict_strip_unicode_keys(data)
        fk_bundle = fk_resource.build_bundle(
            data=data,
            request=request
        )

        if related_obj:
            fk_bundle.related_obj = related_obj
            fk_bundle.related_name = related_name

        # We need to check to see if updates are allowed on the FK
        # resource. If not, we'll just return a populated bundle instead
        # of mistakenly updating something that should be read-only.
        if not fk_resource.can_update():
            return fk_resource.full_hydrate(fk_bundle)

        try:
            fk_bundle.obj =  self.get_obj_from_data(fk_resource, fk_bundle, **data)
        except (NotFound, TypeError):
            try:
                # Attempt lookup by primary key
                lookup_kwargs = dict((k, v) for k, v in data.iteritems() if getattr(fk_resource, k).unique)
                if not lookup_kwargs:
                    raise NotFound()
                fk_bundle.obj = self.get_obj_from_data(fk_resource, fk_bundle, **lookup_kwargs)
            except NotFound:
                pass
        except MultipleObjectsReturned:
            pass
            #return fk_resource.full_hydrate(fk_bundle)

        fk_bundle = fk_resource.full_hydrate(fk_bundle)
        return fk_bundle

    def resource_from_pk(self, fk_resource, obj, request=None, related_obj=None, related_name=None):
        """
        Given an object with a ``pk`` attribute, the related resource
        is attempted to be loaded via that PK.
        """
        bundle = fk_resource.build_bundle(
            obj=obj,
            request=request
        )
        return fk_resource.full_dehydrate(bundle)

    def build_related_resource(self, value, request=None, related_obj=None, related_name=None, orig_bundle=None):
        """
        Returns a bundle of data built by the related resource, usually via
        ``hydrate`` with the data provided.

        Accepts either a URI, a data dictionary (or dictionary-like structure)
        or an object with a ``pk``.
        """
        self.fk_resource = self.get_related_resource(related_obj, orig_bundle)
        kwargs = {
            'request': request,
            'related_obj': related_obj,
            'related_name': related_name,
        }
        if isinstance(value, Bundle):
            # Already hydrated, probably nested bundles. Just return.
            if orig_bundle:
                #dont want to save objects that are pulled from a uri. Cannot have any changes anyway
                orig_bundle.objects_saved.add(self.fk_resource.create_identifier(value.obj))
            return value
        elif isinstance(value, basestring):
            #elif isinstance(value, tuple(self.uri_cls_list)):
            # We got a URI. Load the object and assign it.
            bundle = self.resource_from_uri(self.fk_resource, value, **kwargs)
            if orig_bundle:
                #dont want to save objects that are pulled from a uri. Cannot have any changes anyway
                orig_bundle.objects_saved.add(self.fk_resource.create_identifier(bundle.obj))
            return bundle
        elif hasattr(value, 'items'):
            # We've got a data dictionary.
            # Since this leads to creation, this is the only one of these
            # methods that might care about "parent" data.
            if 'resource_uri' in value:
                bundle = self.resource_from_uri(self.fk_resource, value['resource_uri'], **kwargs)
                if orig_bundle:
                    #dont want to save objects that are pulled from a uri. Cannot have any changes anyway
                    orig_bundle.objects_saved.add(self.fk_resource.create_identifier(bundle.obj))
            else:
                if self.fk_resource._meta.create_on_related_fields:
                    bundle = self.resource_from_data(self.fk_resource, value, **kwargs)
                else:
                    raise ApiFieldError("Related data provided for %s does not have resource_uri field" %self.instance_name)
            return bundle
        elif hasattr(value, 'pk'):
            # We've got an object with a primary key.
            bundle = self.resource_from_pk(self.fk_resource, value, **kwargs)
            if orig_bundle:
                #dont want to save objects that are pulled from a uri. Cannot have any changes anyway
                orig_bundle.objects_saved.add(self.fk_resource.create_identifier(bundle.obj))
            return bundle
        else:
            raise ApiFieldError("The '%s' field was given data that was not a URI, not a dictionary-alike and does not have a 'pk' attribute: %s." % (self.instance_name, value))

    def should_full_dehydrate(self, bundle):
        """
        Based on the ``full``, ``list_full`` and ``detail_full`` returns ``True`` or ``False``
        indicating weather the resource should be fully dehydrated.
        """
        should_dehydrate_full_resource = False
        if self.full:
            #is_details_view = resolve(bundle.request.path).url_name == "api_dispatch_detail"
            is_details_view = getattr(bundle.request, 'request_type', 'list') == 'detail'
            if is_details_view:
                if (not callable(self.full_detail) and self.full_detail) or (callable(self.full_detail) and self.full_detail(bundle)):
                    should_dehydrate_full_resource = True
            else:
                if (not callable(self.full_list) and self.full_list) or (callable(self.full_list) and self.full_list(bundle)):
                    should_dehydrate_full_resource = True

        return should_dehydrate_full_resource


class ToOneField(RelatedField):
    """
    Provides access to related data via foreign key.

    This subclass requires Django's ORM layer to work properly.
    """
    help_text = 'A single related resource. Can be either a URI or set of nested resource data.'

    def __init__(self, to, attribute, related_name=None, default=NOT_PROVIDED,
                 null=False, blank=False, readonly=False, full=False,
                 unique=False, help_text=None, use_in='all', full_list=True,
                 full_detail=True, change_handler=None):
        super(ToOneField, self).__init__(
            to, attribute, related_name=related_name, default=default,
            null=null, blank=blank, readonly=readonly, full=full,
            unique=unique, help_text=help_text, use_in=use_in,
            full_list=full_list, full_detail=full_detail, change_handler=change_handler
        )
        self.fk_resource = None

    def resource_from_data(self, fk_resource, data, request=None, related_obj=None, related_name=None):
        return super(ToOneField, self).resource_from_data(fk_resource, data, request, related_obj, related_name)

    def build_schema(self, **kwargs):

        field_schema = super(ToOneField, self).build_schema(**kwargs)
        related_resource = self.get_related_resource()
        # ASSUMING THAT IF THERE IS NO RESOURCE_URI THEN IT IS
        # A DICTIONARY
        if related_resource._meta.include_resource_uri == False:
            field_schema['type'] = "dict"
        else:
            field_schema['related_type'] = "ToOneField"
            field_schema['schema'] = "%sschema/"%(related_resource.get_resource_uri())

        return field_schema


    def dehydrate(self, bundle):
        foreign_obj = None

        if isinstance(self.attribute, basestring):
            attrs = self.attribute.split('__')
            foreign_obj = bundle.obj

            for attr in attrs:
                previous_obj = foreign_obj
                try:
                    foreign_obj = getattr(foreign_obj, attr, None)
                except ObjectDoesNotExist:
                    foreign_obj = None
        elif callable(self.attribute):
            foreign_obj = self.attribute(bundle)

        if callable(foreign_obj):
            foreign_obj = foreign_obj()

        if not foreign_obj:
            if not self.null:
                raise ApiFieldError("The model '%r' has an empty attribute '%s' and doesn't allow a null value." % (previous_obj, attr))

            return None

        self.fk_resource = self.get_related_resource(foreign_obj, bundle)
        #fk_bundle = self.fk_resource.build_bundle(obj=foreign_obj, request=bundle.request)
        return self.dehydrate_related(bundle, self.fk_resource)

    def hydrate(self, bundle):
        value = super(ToOneField, self).hydrate(bundle)
        kwargs = {}
        if value is None:
            return value
        if self.related_name:
            kwargs['related_obj'] = bundle.obj
            kwargs['related_name'] = self.related_name

        return self.build_related_resource(value, request=bundle.request, orig_bundle=bundle,
                                           **kwargs)

    def save(self, bundle):
        # Get the object.
        try:
            related_obj = getattr(bundle.obj, self.attribute, None)
        except ObjectDoesNotExist:
            related_obj = None

        # Because sometimes it's ``None`` & that's OK.
        if related_obj:
            #Save the main object first before saving the fk
            if self.related_name:
                if not self._resource().get_bundle_detail_data(bundle):
                    bundle.obj.save()

                setattr(related_obj, self.related_name, bundle.obj)

            related_resource = self.get_related_resource(related_obj, bundle)
            # Before we build the bundle & try saving it, let's make sure we
            # haven't already saved it.
            obj_id = related_resource.create_identifier(related_obj)
            if not (obj_id in bundle.objects_saved) and (bundle.data.get(self.instance_name) and hasattr(bundle.data[self.instance_name], 'keys')):
                # Only build & save if there's data, not just a URI.
                related_bundle = related_resource.build_bundle(
                    obj=related_obj,
                    data=bundle.data.get(self.instance_name),
                    request=bundle.request,
                    objects_saved=bundle.objects_saved
                )
                related_resource.save(related_bundle)

            setattr(bundle.obj, self.attribute, related_obj)

        return bundle

class ForeignKey(ToOneField):
    """
    A convenience subclass for those who prefer to mirror ``django.db.models``.
    """
    pass


class OneToOneField(ToOneField):
    """
    A convenience subclass for those who prefer to mirror ``django.db.models``.
    """
    pass


class ToManyField(RelatedField):
    """
    Provides access to related data via a join table.

    This subclass requires Django's ORM layer to work properly.

    Note that the ``hydrate`` portions of this field are quite different than
    any other field. ``hydrate_m2m`` actually handles the data and relations.
    This is due to the way Django implements M2M relationships.
    """
    is_m2m = True
    help_text = 'Many related resources. Can be either a list of URIs or list of individually nested resource data.'

    def __init__(self, to, attribute, related_name=None, default=NOT_PROVIDED,
                 null=False, blank=False, readonly=False, full=False,
                 unique=False, help_text=None, use_in='all', full_list=True,
                 full_detail=True, change_handler=None):
        super(ToManyField, self).__init__(
            to, attribute, related_name=related_name, default=default,
            null=null, blank=blank, readonly=readonly, full=full,
            unique=unique, help_text=help_text, use_in=use_in,
            full_list=full_list, full_detail=full_detail,
            change_handler=change_handler
        )
        self.m2m_bundles = []


    def build_schema(self, **kwargs):
        field_schema = super(ToManyField, self).build_schema(**kwargs)
        related_resource = self.get_related_resource()

        if related_resource._meta.include_resource_uri == False:
            field_schema['type'] = "list"
        else:
            field_schema['related_type'] = "ToManyField"
            field_schema['schema'] = "%sschema/"%(related_resource.get_resource_uri())

        return field_schema

    def dehydrate(self, bundle):
        if not bundle.obj or not bundle.obj.pk:
            if not self.null:
                raise ApiFieldError("The model '%r' does not have a primary key and can not be used in a ToMany context." % bundle.obj)

            return []

        the_m2ms = None
        previous_obj = bundle.obj
        attr = self.attribute

        if isinstance(self.attribute, basestring):
            attrs = self.attribute.split('__')
            the_m2ms = bundle.obj

            for attr in attrs:
                previous_obj = the_m2ms
                try:
                    the_m2ms = getattr(the_m2ms, attr, None)
                except ObjectDoesNotExist:
                    the_m2ms = None

                if not the_m2ms:
                    break

        elif callable(self.attribute):
            the_m2ms = self.attribute(bundle)

        if not the_m2ms:
            if not self.null:
                raise ApiFieldError("The model '%r' has an empty attribute '%s' and doesn't allow a null value." % (previous_obj, attr))

            return []

        self.m2m_resources = []
        m2m_dehydrated = []

        # TODO: Also model-specific and leaky. Relies on there being a
        #       ``Manager`` there
        for m2m in the_m2ms.all():
            m2m_resource = self.get_related_resource(m2m, bundle)
            #m2m_bundle = m2m_resource.build_bundle(obj=m2m, request=bundle.request)
            self.m2m_resources.append(m2m_resource)
            m2m_dehydrated.append(self.dehydrate_related(bundle, m2m_resource))
        return m2m_dehydrated

    def hydrate(self, bundle):
        pass

    def hydrate_m2m(self, bundle):
        if self.readonly:
            return None

        if bundle.data.get(self.instance_name) is None:
            if self.blank:
                return []
            elif self.null:
                return []
            else:
                raise ApiFieldError("The '%s' field has no data and doesn't allow a null value." % self.instance_name)

        m2m_hydrated = []

        value_list = bundle.data.get(self.instance_name)
        if not isinstance(value_list,list):
            raise ApiFieldError("The '%s' field has to be list." % self.instance_name)
        for value in value_list:
            if value is None:
                continue

            kwargs = {
                'request': bundle.request,
                'orig_bundle' : bundle
            }

            if self.related_name:
                kwargs['related_obj'] = bundle.obj
                kwargs['related_name'] = self.related_name

            m2m_hydrated.append(self.build_related_resource(value, **kwargs))
        return m2m_hydrated


    def get_related_mngr(self, bundle):
        related_mngr = None
        if isinstance(self.attribute, basestring):
            current_obj = bundle.obj
            for attr in self.attribute.split('__'):
                try:
                    current_obj = getattr(current_obj, attr)
                    related_mngr = current_obj
                except ObjectDoesNotExist:
                    return None
        elif callable(self.attribute):
            related_mngr = self.attribute(bundle)

        return related_mngr

    def get_related_objs(self, bundle):
        related_objs = []
        for related_bundle in bundle.data[self.instance_name]:
            related_resource = self.get_related_resource(bundle.obj, bundle)

            # Before we build the bundle & try saving it, let's make sure we
            # haven't already saved it.
            obj_id = related_resource.create_identifier(related_bundle.obj)

            if obj_id in bundle.objects_saved:
                # It's already been saved. We're done here.
                related_objs.append(related_bundle.obj)
                continue
            # Only build & save if there's data, not just a URI.
            updated_related_bundle = related_resource.build_bundle(
                obj=related_bundle.obj,
                data=related_bundle.data,
                request=bundle.request,
                objects_saved=bundle.objects_saved
            )
            related_bundle = related_resource.save(updated_related_bundle)
            related_objs.append(related_bundle.obj)
        return related_objs


    def save(self, bundle):
        related_mngr = self.get_related_mngr(bundle)
        if not related_mngr:
            return

        related_objs = self.get_related_objs(bundle)

        for obj in related_mngr.all():
            if obj not in related_objs:
                related_mngr.remove(obj)

        for obj in related_objs:
            if obj not in related_mngr.all():
                related_mngr.add(obj)



class ManyToManyField(ToManyField):
    """
    A convenience subclass for those who prefer to mirror ``django.db.models``.
    """
    pass


class OneToManyField(ToManyField):
    """
    A convenience subclass for those who prefer to mirror ``django.db.models``.
    """
    pass

class BaseSubResourceField(object):

    def get_related_resource(self, related_instance=None, bundle=None):
        """
        Instaniates the related resource.
        """
        related_resource = super(BaseSubResourceField, self).get_related_resource(related_instance, bundle)
        if bundle:
            related_resource.parent_resource = bundle.resource
            related_resource.parent_pk = bundle.obj.pk
            related_resource.parent_obj = bundle.obj
            related_resource.parent_field = self.instance_name

        return related_resource


class ToOneSubResourceField(BaseSubResourceField, ToOneField):
    def __init__(self, *args, **kwargs):
        kwargs['readonly'] = True
        super(ToOneSubResourceField, self).__init__(*args, **kwargs)

    def build_schema(self, **kwargs):
        field_schema = super(ToOneSubResourceField, self).build_schema(**kwargs)
        field_schema['related_type'] = "ToOneSubResourceField"

        related_resource = self.get_related_resource()

        field_schema['schema'] = "%s%s/schema/"%(kwargs['resource_uri'], related_resource._meta.resource_name)

        return field_schema


class ToManySubResourceField(BaseSubResourceField, ToManyField):
    def __init__(self, *args, **kwargs):
        kwargs['readonly'] = True
        if not 'related_name' in kwargs:
            raise TypeError('Please specify a related name')
        super(ToManySubResourceField, self).__init__(*args, **kwargs)

    def build_schema(self, **kwargs):
        field_schema = super(ToManySubResourceField, self).build_schema(**kwargs)

        field_schema['related_type'] = "ToManySubResourceField"
        related_resource = self.get_related_resource()
        field_schema['schema'] = "%s%s/schema/"%(kwargs['resource_uri'], related_resource._meta.resource_name)
        return field_schema


    def dehydrate(self, bundle):
        if not bundle.obj or not bundle.obj.pk:
            if not self.null:
                raise ApiFieldError("The model '%r' does not have a primary key and can not be used in a SubResource context." % bundle.obj)

            return []

        the_m2ms = None
        previous_obj = bundle.obj
        attr = self.attribute

        if isinstance(self.attribute, basestring):
            attrs = self.attribute.split('__')
            the_m2ms = bundle.obj

            for attr in attrs:
                previous_obj = the_m2ms
                try:
                    the_m2ms = getattr(the_m2ms, attr, None)
                except ObjectDoesNotExist:
                    the_m2ms = None

                if not the_m2ms:
                    break

        elif callable(self.attribute):
            the_m2ms = self.attribute(bundle)

        if not the_m2ms:
            if not self.null:
                raise ApiFieldError("The model '%r' has an empty attribute '%s' and doesn't allow a null value." % (previous_obj, attr))

            return []

        self.m2m_resources = []
        m2m_dehydrated = []

        # TODO: Also model-specific and leaky. Relies on there being a
        #       ``Manager`` there
        related_resource = self.get_related_resource(related_instance=None, bundle=bundle)
        authorized_object_list = related_resource.authorized_read_list(the_m2ms.all(), bundle)

        for m2m in authorized_object_list:
            m2m_resource = self.get_related_resource(m2m, bundle)
            #m2m_bundle = m2m_resource.build_bundle(obj=m2m, request=bundle.request)
            self.m2m_resources.append(m2m_resource)
            m2m_dehydrated.append(self.dehydrate_related(bundle, m2m_resource))
        return m2m_dehydrated














class TimeField(ApiField):
    dehydrated_type = 'time'
    help_text = 'A time as string. Ex: "20:05:23"'

    def dehydrate(self, obj):
        return self.convert(super(TimeField, self).dehydrate(obj))

    def convert(self, value):
        if isinstance(value, basestring):
            return self.to_time(value)
        return value

    def to_time(self, s):
        try:
            dt = parse(s)
        except ValueError, e:
            raise ApiFieldError(str(e))
        else:
            return datetime.time(dt.hour, dt.minute, dt.second)

    def hydrate(self, bundle):
        value = super(TimeField, self).hydrate(bundle)

        if value and not isinstance(value, datetime.time):
            value = self.to_time(value)

        return value
