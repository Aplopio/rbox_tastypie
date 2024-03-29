from __future__ import unicode_literals
from __future__ import with_statement
from past.builtins import basestring
from builtins import object
import simplejson
from copy import deepcopy
import logging
import warnings

from django.conf import settings

from tastypie.utils import IS_DJANGO_1_4
if IS_DJANGO_1_4:
    from django.conf.urls import url, patterns, include
else:
    from django.conf.urls import url, include

from django.core.exceptions import (
    ObjectDoesNotExist, MultipleObjectsReturned, ValidationError, ImproperlyConfigured, FieldDoesNotExist
)
from django.urls import NoReverseMatch, reverse, resolve, Resolver404, get_script_prefix, reverse_lazy
from django.core.signals import got_request_exception
from django.db import transaction
try:
    from django.db.models.constants import LOOKUP_SEP
except ImportError:
    from django.db.models.sql.constants import LOOKUP_SEP

from django.http import HttpResponse, HttpResponseNotFound, Http404
from django.utils.cache import patch_cache_control, patch_vary_headers
import six

from tastypie.authentication import Authentication
from tastypie.authorization import ReadOnlyAuthorization
from tastypie.bundle import Bundle
from tastypie.cache import NoCache
from tastypie.constants import ALL, ALL_WITH_RELATIONS
from tastypie.exceptions import NotFound, BadRequest, InvalidFilterError, HydrationError, InvalidSortError, ImmediateResponse, Unauthorized, Forbidden, UnsupportedFormat
from tastypie import fields
from tastypie import http
from tastypie.paginator import Paginator
from tastypie.serializers import Serializer
from tastypie.throttle import BaseThrottle
from tastypie.utils import is_valid_jsonp_callback_value, dict_strip_unicode_keys, trailing_slash
from tastypie.utils.mime import determine_format, build_content_type
from tastypie.utils import get_current_func_name, get_request_class
from tastypie.validation import Validation
from tastypie.event_handler import EventHandler
from tastypie.bundle_pre_processor import BundlePreProcessor
from tastypie import response_router_obj
from django.core.exceptions import ImproperlyConfigured
from django.urls.resolvers import URLResolver as RegexURLResolver, RegexPattern
from django.core.signals import got_request_exception

from copy import copy

from bson import ObjectId
from tastypie.bundle import Bundle


try:
    commit_on_success = transaction.atomic
except AttributeError:
    commit_on_success = transaction.commit_on_success

try:
    set
except NameError:
    from sets import Set as set

# If ``csrf_exempt`` isn't present, stub it.
try:
    from django.views.decorators.csrf import csrf_exempt
except ImportError:
    def csrf_exempt(func):
        return func



class NOT_AVAILABLE(object):
    def __str__(self):
        return 'No such data is available.'


class CustomRegexURLResolver(RegexURLResolver):
    @property
    def url_patterns(self):
        if IS_DJANGO_1_4:
            url_patterns = patterns("", *self.urlconf_name)
        else:
            url_patterns = self.urlconf_name
        try:
            iter(url_patterns)
        except TypeError:
            raise ImproperlyConfigured("The included urlconf %s doesn't have any patterns in it" % self.urlconf_name)
        return url_patterns



class ResourceOptions(object):
    """
    A configuration class for ``Resource``.

    Provides sane defaults and the logic needed to augment these settings with
    the internal ``class Meta`` used on ``Resource`` subclasses.
    """
    response_router_obj  = response_router_obj
    serializer = Serializer()
    authentication = Authentication()
    authorization = ReadOnlyAuthorization()
    bundle_pre_processor = BundlePreProcessor()
    event_handler = EventHandler()

    cache = NoCache()
    throttle = BaseThrottle()
    validation = Validation()
    paginator_class = Paginator
    allowed_methods = ['get', 'post', 'put', 'delete', 'patch']
    list_allowed_methods = None
    detail_allowed_methods = None
    limit = getattr(settings, 'API_LIMIT_PER_PAGE', 20)
    max_limit = 1000
    api_name = None
    resource_name = None
    urlconf_namespace = None
    default_format = 'application/json'
    filtering = {}
    ordering = []
    object_class = None
    queryset = None
    fields = []
    excludes = []
    include_resource_uri = True
    include_absolute_url = False
    always_return_data = False
    collection_name = 'objects'
    detail_uri_name = 'pk'
    create_on_related_fields = False

    prefetch_related = []
    select_related = []

    def __new__(cls, meta=None):
        overrides = {}

        # Handle overrides.
        if meta:
            for override_name in dir(meta):
                # No internals please.
                if not override_name.startswith('_'):
                    overrides[override_name] = getattr(meta, override_name)

        allowed_methods = overrides.get('allowed_methods', ['get', 'post', 'put', 'delete', 'patch'])

        if overrides.get('list_allowed_methods', None) is None:
            overrides['list_allowed_methods'] = allowed_methods

        if overrides.get('detail_allowed_methods', None) is None:
            overrides['detail_allowed_methods'] = allowed_methods

        if six.PY3:
            return object.__new__(type('ResourceOptions', (cls,), overrides))
        else:
            return object.__new__(type(b'ResourceOptions', (cls,), overrides))


class DeclarativeMetaclass(type):
    def __new__(cls, name, bases, attrs):
        attrs['base_fields'] = {}
        declared_fields = {}

        # Inherit any fields from parent(s).
        try:
            parents = [b for b in bases if issubclass(b, Resource)]
            # Simulate the MRO.
            parents.reverse()

            for p in parents:
                parent_fields = getattr(p, 'base_fields', {})

                for field_name, field_object in list(parent_fields.items()):
                    attrs['base_fields'][field_name] = deepcopy(field_object)
        except NameError:
            pass

        for field_name, obj in list(attrs.copy().items()):
            # Look for ``dehydrated_type`` instead of doing ``isinstance``,
            # which can break down if Tastypie is re-namespaced as something
            # else.
            if hasattr(obj, 'dehydrated_type'):
                field = attrs.pop(field_name)
                declared_fields[field_name] = field

        attrs['base_fields'].update(declared_fields)
        attrs['declared_fields'] = declared_fields
        new_class = super(DeclarativeMetaclass, cls).__new__(cls, name, bases, attrs)
        opts = getattr(new_class, 'Meta', None)
        new_class._meta = ResourceOptions(opts)

        if not getattr(new_class._meta, 'resource_name', None):
            # No ``resource_name`` provided. Attempt to auto-name the resource.
            class_name = new_class.__name__
            name_bits = [bit for bit in class_name.split('Resource') if bit]
            resource_name = ''.join(name_bits).lower()
            new_class._meta.resource_name = resource_name

        if getattr(new_class._meta, 'include_resource_uri', True):
            if not 'resource_uri' in new_class.base_fields:
                new_class.base_fields['resource_uri'] = fields.CharField(readonly=True)
        elif 'resource_uri' in new_class.base_fields and not 'resource_uri' in attrs:
            del(new_class.base_fields['resource_uri'])

        for field_name, field_object in list(new_class.base_fields.items()):
            if hasattr(field_object, 'contribute_to_class'):
                field_object.contribute_to_class(new_class, field_name)

        return new_class


class Resource(six.with_metaclass(DeclarativeMetaclass)):
    """
    Handles the data, request dispatch and responding to requests.

    Serialization/deserialization is handled "at the edges" (i.e. at the
    beginning/end of the request/response cycle) so that everything internally
    is Python data structures.

    This class tries to be non-model specific, so it can be hooked up to other
    data sources, such as search results, files, other data, etc.
    """
    def __init__(self, api_name=None, parent_resource=None, parent_pk=None, parent_obj=None, parent_field=None):
        self.fields = {k: copy(v) for k, v in self.base_fields.items()}
        self.parent_resource=parent_resource
        self.parent_pk = parent_pk
        self.parent_obj = parent_obj
        self.parent_field = parent_field
        if not api_name is None:
            self._meta.api_name = api_name

    def __getattr__(self, name):
        if name in self.fields:
            return self.fields[name]
        raise AttributeError(name)

    def resource_parent_uri_kwargs(self, parent_resource, parent_pk):
        if not parent_resource:
            return {}
        else:
            kwargs = parent_resource.resource_parent_uri_kwargs(parent_resource.parent_resource,
                                                              parent_resource.parent_pk)
            kwargs.update({
                '%s_resource_name'%parent_resource._meta.resource_name: parent_resource._meta.resource_name,
                '%s_pk'%parent_resource._meta.resource_name: parent_pk

            })
            return kwargs

    def wrap_view(self, view):
        """
        Wraps methods so they can be called in a more functional way as well
        as handling exceptions better.

        Note that if ``BadRequest`` or an exception with a ``response`` attr
        are seen, there is special handling to either present a message back
        to the user or return the response traveling with the exception.
        """

        @csrf_exempt
        def wrapper(request, *args, **kwargs):

            try:
                callback = getattr(self, view)
                response = callback(request, *args, **kwargs)
                # Our response can vary based on a number of factors, use
                # the cache class to determine what we should ``Vary`` on so
                # caches won't return the wrong (cached) version.
                varies = getattr(self._meta.cache, "varies", [])

                if varies:
                    response = self._meta.response_router_obj[request].handle_vary_headers(response,varies)

                if self._meta.cache.cacheable(request, response):
                    if self._meta.cache.cache_control():
                        # If the request is cacheable and we have a
                        # ``Cache-Control`` available then patch the header.
                        response = self._meta.response_router_obj[request].handle_cache_control(response, **self._meta.cache.cache_control())

                if request.is_ajax() and not response.has_header("Cache-Control"):
                    # IE excessively caches XMLHttpRequests, so we're disabling
                    # the browser cache here.
                    # See http://www.enhanceie.com/ie/bugs.asp for details.
                    response = self._meta.response_router_obj[request].handle_cache_control(response, no_cache=True)

                return response
            except (BadRequest, fields.ApiFieldError) as e:
                data = {"error": e.args[0] if getattr(e, 'args') else ''}
                return self.error_response(request, data, response_class=self._meta.response_router_obj[request].get_bad_request_response_class())
            except ValidationError as e:
                data = {"error": e.messages}
                return self.error_response(request, data, response_class=self._meta.response_router_obj[request].get_bad_request_response_class())
            except Exception as e:
                return self._handle_500(request, e)

        return wrapper

    def _handle_500(self, request, exception):
        method = getattr(self, '%s_%s' % ('_handle_500', get_request_class(request)))
        return method(request, exception)

    def _handle_500_wsgirequest(self, request, exception):

        if hasattr(exception, 'response'):
            return exception.response

        # A real, non-expected exception.
        # Handle the case where the full traceback is more helpful
        # than the serialized error.
        if settings.DEBUG and getattr(settings, 'TASTYPIE_FULL_DEBUG', False):
            raise

        # Re-raise the error to get a proper traceback when the error
        # happend during a test case
        if request.META.get('SERVER_NAME') == 'testserver':
            raise

        # Rather than re-raising, we're going to things similar to
        # what Django does. The difference is returning a serialized
        # error message.

        import traceback
        import sys
        the_trace = '\n'.join(traceback.format_exception(*(sys.exc_info())))
        response_class = self._meta.response_router_obj[request].get_application_error_class()
        response_code = 500

        NOT_FOUND_EXCEPTIONS = (NotFound, ObjectDoesNotExist, Http404)

        if isinstance(exception, NOT_FOUND_EXCEPTIONS):
            response_class = self._meta.response_router_obj[request].get_response_notfound_class()
            response_code = 404

        if settings.DEBUG:
            data = {
                "error_message": six.text_type(exception),
                "traceback": the_trace,
            }
            return self.error_response(request, data, response_class=response_class)

        # When DEBUG is False, send an error message to the admins (unless it's
        # a 404, in which case we check the setting).
        send_broken_links = getattr(settings, 'SEND_BROKEN_LINK_EMAILS', False)

        if not response_code == 404 or send_broken_links:
            log = logging.getLogger('django.request.tastypie')
            log.error('Internal Server Error: %s' % request.path, exc_info=True,
                      extra={'status_code': response_code, 'request': request})

        # Send the signal so other apps are aware of the exception.
        got_request_exception.send(self.__class__, request=request)

        # Prep the data going out.
        data = {
            "error_message":getattr(settings, 'TASTYPIE_CANNED_ERROR', "Sorry, this request could not be processed. Please try again later."),
        }
        return self.error_response(request, data, response_class=response_class)

    def _build_reverse_url(self, name, args=None, kwargs=None):
        """
        A convenience hook for overriding how URLs are built.

        See ``NamespacedModelResource._build_reverse_url`` for an example.
        """
        return reverse(name, args=args, kwargs=kwargs)

    def base_urls(self):
        """
        The standard URLs this ``Resource`` should respond to.
        """
        return [
            url(r"^(?P<resource_name>%s)%s$" % (self._meta.resource_name, trailing_slash()), self.wrap_view('dispatch_list'), name="api_dispatch_list"),
            url(r"^(?P<resource_name>%s)/schema%s$" % (self._meta.resource_name, trailing_slash()), self.wrap_view('get_schema'), name="api_get_schema"),
            url(r"^(?P<resource_name>%s)/set/(?P<%s_list>\w[\w/;-]*)%s$" % (self._meta.resource_name, self._meta.detail_uri_name, trailing_slash()), self.wrap_view('get_multiple'), name="api_get_multiple"),
            url(r"^(?P<resource_name>%s)/(?P<%s>\w+)%s$" % (self._meta.resource_name, self._meta.detail_uri_name, trailing_slash()), self.wrap_view('dispatch_detail'), name="api_dispatch_detail"),
        ]

    def override_urls(self):
        """
        Deprecated. Will be removed by v1.0.0. Please use ``prepend_urls`` instead.
        """
        return []

    def prepend_urls(self):
        """
        A hook for adding your own URLs or matching before the default URLs.
        """
        return []

    def view_to_handle_subresource(self, request, **kwargs):
        sub_resource_field_list = kwargs.pop('%s_sub_resource_field_list'%self._meta.resource_name)
        rest_of_url = kwargs.pop('%s_rest_of_url'%self._meta.resource_name)
        pk = kwargs.pop('pk')

        self.is_authenticated(request)
        self.throttle_check(request)
        try:
            parent_bundle = self.build_bundle(request=request)
            parent_obj = self.obj_get(
                parent_bundle, **{
                    self._meta.detail_uri_name: pk
                })
        except (ImmediateResponse) as e:
            raise e
        except Exception:
            return self._meta.response_router_obj[request].get_not_found_response()

        for field in sub_resource_field_list:
            sub_resource_obj = field.get_related_resource(parent_obj, parent_bundle)

            resolver = CustomRegexURLResolver(RegexPattern(r'^'), sub_resource_obj.urls)
            try:
                if rest_of_url[-1] != '/':
                    rest_of_url = "%s%s" %(rest_of_url, trailing_slash())
                callback, callback_args, callback_kwargs = resolver.resolve(rest_of_url)
                callback_kwargs.update({'%s_resource_name'%self._meta.resource_name: self._meta.resource_name, '%s_pk'%self._meta.resource_name: pk, 'api_name': self._meta.api_name})
                try:
                    manager = parent_obj
                    for att in field.attribute.split('__'):
                        manager=getattr(manager,att)
                    sub_resource_obj._meta.queryset = manager.all()
                except AttributeError: #Happens when this is ToOneSubResourceField
                    if manager:
                        sub_resource_obj._meta.queryset = sub_resource_obj._meta.queryset.model.objects.filter(pk=manager.id)
                        #manager refers to the one to one id
                        #doing it via model.objects due to cache problems
                    else:
                        sub_resource_obj._meta.queryset = sub_resource_obj._meta.queryset.none()
                except ObjectDoesNotExist:
                    sub_resource_obj._meta.queryset = sub_resource_obj._meta.queryset._clone().none()

                return callback(request, *callback_args, **callback_kwargs)
            except Http404:
                pass
        return self._meta.response_router_obj[request].get_not_found_response()


    def sub_resource_urls(self):
        sub_resource_field_list = []
        url_list=[]

        for name, field in list(self.fields.items()):
            if isinstance(field, fields.BaseSubResourceField):
                url_list += [url(r"^(?P<resource_name>%s)/(?P<sub_resource_name>.+)/schema/"%(self._meta.resource_name,), self.wrap_view('build_sub_resource_schema'), name="%s_%s_schema"%(self._meta.resource_name,field.get_related_resource()._meta.resource_name) )]
                sub_resource_field_list.append(field)

        if len(sub_resource_field_list) > 0:
            url_list += [
                url(r"^(?P<resource_name>%s)/(?P<pk>\w+)/(?P<%s_rest_of_url>.+)"%(self._meta.resource_name,
                                                                                       self._meta.resource_name),
                    self.wrap_view('view_to_handle_subresource'), {'%s_sub_resource_field_list'%(self._meta.resource_name): sub_resource_field_list}),
            ]

        for name, field in list(self.fields.items()):
            if isinstance(field, fields.BaseSubResourceField):
                include_urls = include(field.get_related_resource().urls)
                url_list += [
                    url(r"^(?P<%s_resource_name>%s)/(?P<%s_pk>\w+)/"%(self._meta.resource_name, self._meta.resource_name, self._meta.resource_name), include_urls),

                           ]
        return url_list


    def build_sub_resource_schema(self,request,*args,**kwargs):
        sub_resource = kwargs['sub_resource_name']
        parent_resource = self
        for sub_resource_name in sub_resource.split("/"):
            resource = parent_resource.fields[sub_resource_name].get_related_resource()
            resource.parent_resource = parent_resource
            parent_resource = resource
        data = resource.build_schema()
        return self.create_response(request, data)

    @property
    def urls(self):
        """
        The endpoints this ``Resource`` responds to.

        Mostly a standard URLconf, this is suitable for either automatic use
        when registered with an ``Api`` class or for including directly in
        a URLconf should you choose to.
        """
        urls = self.prepend_urls()


        overridden_urls = self.override_urls()
        if overridden_urls:
            warnings.warn("'override_urls' is a deprecated method & will be removed by v1.0.0. Please rename your method to ``prepend_urls``.")
            urls += overridden_urls

        urls += self.base_urls()
        urls += self.sub_resource_urls()
        return urls

    def determine_format(self, request):
        """
        Used to determine the desired format.

        Largely relies on ``tastypie.utils.mime.determine_format`` but here
        as a point of extension.
        """
        return determine_format(request, self._meta.serializer, default_format=self._meta.default_format)

    def serialize(self, request, data, format, options=None):
        """
        Given a request, data and a desired format, produces a serialized
        version suitable for transfer over the wire.

        Mostly a hook, this uses the ``Serializer`` from ``Resource._meta``.
        """
        options = options or {}

        if 'text/javascript' in format:
            # get JSONP callback name. default to "callback"
            callback = request.GET.get('callback', 'callback')

            if not is_valid_jsonp_callback_value(callback):
                raise BadRequest('JSONP callback name is invalid.')

            options['callback'] = callback

        return self._meta.serializer.serialize(data, format, options)

    def deserialize(self, request, data, format='application/json'):
        """
        Given a request, data and a format, deserializes the given data.

        It relies on the request properly sending a ``CONTENT_TYPE`` header,
        falling back to ``application/json`` if not provided.

        Mostly a hook, this uses the ``Serializer`` from ``Resource._meta``.
        """
        try:
            deserialized = self._meta.serializer.deserialize(data, format=request.META.get('CONTENT_TYPE', 'application/json'))
        except UnsupportedFormat as e:
            errors = {"errors": e.message}
            raise ImmediateResponse(response=self.error_response(request, errors))
        except ValueError as e:
            errors = {"errors": "Please provide a proper JSON string!"}
            raise ImmediateResponse(response=self.error_response(request, errors))
        return deserialized

    def alter_list_data_to_serialize(self, request, data):
        """
        A hook to alter list data just before it gets serialized & sent to the user.

        Useful for restructuring/renaming aspects of the what's going to be
        sent.

        Should accommodate for a list of objects, generally also including
        meta data.
        """
        return data

    def alter_detail_data_to_serialize(self, request, data):
        """
        A hook to alter detail data just before it gets serialized & sent to the user.

        Useful for restructuring/renaming aspects of the what's going to be
        sent.

        Should accommodate for receiving a single bundle of data.
        """
        return data

    def alter_deserialized_list_data(self, request, data):
        """
        A hook to alter list data just after it has been received from the user &
        gets deserialized.

        Useful for altering the user data before any hydration is applied.
        """
        return data

    def alter_deserialized_detail_data(self, request, data):
        """
        A hook to alter detail data just after it has been received from the user &
        gets deserialized.

        Useful for altering the user data before any hydration is applied.
        """
        return data

    def dispatch_list(self, request, **kwargs):
        """
        A view for handling the various HTTP methods (GET/POST/PUT/DELETE) over
        the entire list of resources.

        Relies on ``Resource.dispatch`` for the heavy-lifting.
        """
        return self.dispatch('list', request, **kwargs)

    def dispatch_detail(self, request, **kwargs):
        """
        A view for handling the various HTTP methods (GET/POST/PUT/DELETE) on
        a single resource.

        Relies on ``Resource.dispatch`` for the heavy-lifting.
        """
        return self.dispatch('detail', request, **kwargs)

    def dispatch(self, request_type, request, **kwargs):
        """
        Handles the common operations (allowed HTTP method, authentication,
        throttling, method lookup) surrounding most CRUD interactions.
        """
        allowed_methods = getattr(self._meta, "%s_allowed_methods" % request_type, None)

        if 'HTTP_X_HTTP_METHOD_OVERRIDE' in request.META:
            request.method = request.META['HTTP_X_HTTP_METHOD_OVERRIDE']

        request_method = self.method_check(request, allowed=allowed_methods)
        method = getattr(self, "%s_%s" % (request_method, request_type), None)

        if method is None:
            raise ImmediateResponse(response= self._meta.response_router_obj[request].get_not_implemented_response())

        self.is_authenticated(request)
        self.throttle_check(request)

        # All clear. Process the request.
        request = convert_post_to_put(request)
        response = method(request, **kwargs)

        # RK: Set request_type on request
        setattr(request, 'request_type', request_type)

        # Add the throttled request.
        self.log_throttled_access(request)

        # If what comes back isn't a ``HttpResponse``, assume that the
        # request was accepted and that some action occurred. This also
        # prevents Django from freaking out.

        ##if not isinstance(response,  self._meta.response_router_obj[request].get_response_class())
        ##return  self._meta.response_router_obj[request].get_no_content_response()

        return response

    def remove_api_resource_names(self, url_dict):
        """
        Given a dictionary of regex matches from a URLconf, removes
        ``api_name`` and/or ``resource_name`` if found.

        This is useful for converting URLconf matches into something suitable
        for data lookup. For example::

            Model.objects.filter(**self.remove_api_resource_names(matches))
        """
        kwargs_subset = url_dict.copy()

        for key in ['api_name', 'resource_name']:
            try:
                del(kwargs_subset[key])
            except KeyError:
                pass
        for key, item in url_dict.items():
            if 'resource_name' in key or (key !='pk' and 'pk' in key):
                try:
                    del (kwargs_subset[key])
                except KeyError:
                    pass
        return kwargs_subset

    def method_check(self, request, allowed=None):
        """
        Ensures that the HTTP method used on the request is allowed to be
        handled by the resource.

        Takes an ``allowed`` parameter, which should be a list of lowercase
        HTTP methods to check against. Usually, this looks like::

            # The most generic lookup.
            self.method_check(request, self._meta.allowed_methods)

            # A lookup against what's allowed for list-type methods.
            self.method_check(request, self._meta.list_allowed_methods)

            # A useful check when creating a new endpoint that only handles
            # GET.
            self.method_check(request, ['get'])
        """
        if allowed is None:
            allowed = []

        request_method = request.method.lower()
        allows = ','.join([meth.upper() for meth in allowed])

        if request_method == "options":
            response_class = self._meta.response_router_obj[request].get_default_response_class()
            response = response_class(allows)
            response['Allow'] = allows
            raise ImmediateResponse(response=response)

        if not request_method in allowed:
            response = self._meta.response_router_obj[request].get_method_notallowed_response(allows)
            response['Allow'] = allows
            raise ImmediateResponse(response=response)

        return request_method

    def is_authenticated(self, request):
        """
        Handles checking if the user is authenticated and dealing with
        unauthenticated users.

        Mostly a hook, this uses class assigned to ``authentication`` from
        ``Resource._meta``.
        """
        # Authenticate the request as needed.
        auth_result = self._meta.authentication.is_authenticated(request)
        if not auth_result is True:
            raise ImmediateResponse(self._meta.response_router_obj[request].get_unauthorized_request_response())

    def throttle_check(self, request):
        """
        Handles checking if the user should be throttled.

        Mostly a hook, this uses class assigned to ``throttle`` from
        ``Resource._meta``.
        """
        method = getattr(self, '%s_%s' %('throttle_check', get_request_class(request)))
        return method(request)

    def throttle_check_wsgirequest(self, request):

        identifier = self._meta.authentication.get_identifier(request)

        # Check to see if they should be throttled.
        if self._meta.throttle.should_be_throttled(identifier):
            # Throttle limit exceeded.
            raise ImmediateResponse(response= self._meta.response_router_obj[request].get_too_many_request_response())

    def log_throttled_access(self, request):
        """
        Handles the recording of the user's access for throttling purposes.

        Mostly a hook, this uses class assigned to ``throttle`` from
        ``Resource._meta``.
        """
        method = getattr(self, '%s_%s' %('log_throttled_access', get_request_class(request)))
        return method(request)

    def log_throttled_access_wsgirequest(self, request):
        request_method = request.method.lower()
        self._meta.throttle.accessed(self._meta.authentication.get_identifier(request), url=request.get_full_path(), request_method=request_method)

    def paginate(self, bundle, object_list):
        request = bundle.request
        paginator = self._meta.paginator_class(request.GET, object_list, resource_uri=self.get_resource_uri(),
                limit=self._meta.limit, max_limit=self._meta.max_limit, collection_name=self._meta.collection_name)
        return paginator.page()

    def is_authorized(self, action,object_list, bundle ):
        try:
            auth_result = getattr(self._meta.authorization, action)(object_list, bundle)
        except Unauthorized as exception:
            response = self._meta.response_router_obj[bundle.request].get_unauthorized_request_response()
            response.content = exception.message
            raise ImmediateResponse(response=response)

            #self.unauthorized_result(bundle.request, e)
        except Forbidden as exception:

            response_class = self._meta.response_router_obj[bundle.request].get_forbidden_response_class()
            errors = {"error_type":exception.error_type,
                     "error_message":exception.error_message}
            response=self.error_response(bundle.request, errors, response_class=response_class)
            raise ImmediateResponse(response)
            #self.forbidden_result(bundle.request,e)
        return auth_result

    def authorized_read_list(self, object_list, bundle):
        """
        DEPRECATED
        """
        return self.is_authorized("read_list", object_list, bundle)

    def authorized_read_detail(self, object_list, bundle):
        """
        DEPRECATED
        """
        return self.is_authorized("read_detail", object_list, bundle)

    def authorized_create_list(self, object_list, bundle):
        """
        DEPRECATED
        """
        return self.is_authorized("create_detail", object_list, bundle)

    def authorized_create_detail(self, object_list, bundle):
        """
        DEPRECATED
        """
        return self.is_authorized("create_detail", object_list, bundle)

    def authorized_update_list(self, object_list, bundle):
        """
        DEPRECATED
        """
        return self.is_authorized("update_list", object_list, bundle)

    def authorized_update_detail(self, object_list, bundle):
        """
        DEPRECATED
        """
        return self.is_authorized("update_detail", object_list, bundle)

    def authorized_delete_list(self, object_list, bundle):
        """
        DEPRECATED
        """
        return self.is_authorized("delete_list", object_list, bundle)

    def authorized_delete_detail(self, object_list, bundle):
        """
        DEPRECATED
        """
        return self.is_authorized("delete_detail", object_list, bundle)

    def preprocess(self, event_type, bundle):
        """
        Handles pre processing. Event manager object implemented in a
        subclass can handle doing appropriate work
        """
        pre_processor = getattr(self._meta.bundle_pre_processor, event_type, None) if self._meta.bundle_pre_processor else None
        if pre_processor:
            #event function modifies the bundle, object_list
            bundle = pre_processor(bundle)
        return bundle


    def fire_event(self, event_type, args=()):
        """
        Handles generation of event. Event manager object implemented in a
        subclass can handle doing appropriate work
        """
        object_list, bundle = args
        event_function = getattr(self._meta.event_handler, event_type, None) if self._meta.event_handler else None
        if event_function:
            event_function(object_list, bundle)


    def build_bundle(self, obj=None, data=None, request=None, objects_saved=None):
        """
        Given either an object, a data dictionary or both, builds a ``Bundle``
        for use throughout the ``dehydrate/hydrate`` cycle.

        If no object is provided, an empty object from
        ``Resource._meta.object_class`` is created so that attempts to access
        ``bundle.obj`` do not fail.
        """
        if obj is None and self._meta.object_class:
            obj = self._meta.object_class()

        return Bundle(
            obj=obj,
            data=data,
            request=request,
            resource=self,
            objects_saved=objects_saved,
            parent_obj=self.parent_obj,
            parent_resource = self.parent_resource
        )

    def build_filters(self, filters=None, bundle=None):
        """
        Allows for the filtering of applicable objects.

        This needs to be implemented at the user level.'

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        return filters

    def apply_sorting(self, obj_list, options=None):
        """
        Allows for the sorting of objects being returned.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        return obj_list

    def get_bundle_detail_data(self, bundle):
        """
        Convenience method to return the ``detail_uri_name`` attribute off
        ``bundle.obj``.

        Usually just accesses ``bundle.obj.pk`` by default.
        """
        return getattr(bundle.obj, self._meta.detail_uri_name)

    # URL-related methods.

    def detail_uri_kwargs(self, bundle_or_obj):
        """
        This needs to be implemented at the user level.

        Given a ``Bundle`` or an object, it returns the extra kwargs needed to
        generate a detail URI.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def resource_uri_kwargs(self, bundle_or_obj=None):
        """
        Builds a dictionary of kwargs to help generate URIs.

        Automatically provides the ``Resource.Meta.resource_name`` (and
        optionally the ``Resource.Meta.api_name`` if populated by an ``Api``
        object).

        If the ``bundle_or_obj`` argument is provided, it calls
        ``Resource.detail_uri_kwargs`` for additional bits to create
        """

        kwargs = {
            'resource_name': self._meta.resource_name,
        }

        if self._meta.api_name is not None:
            kwargs['api_name'] = self._meta.api_name
        if bundle_or_obj is not None:
            kwargs.update(self.detail_uri_kwargs(bundle_or_obj))
        kwargs.update(self.resource_parent_uri_kwargs(self.parent_resource, self.parent_pk))
        return kwargs

    def get_resource_uri(self, bundle_or_obj=None, **kwargs):
        """
        Handles generating a resource URI.

        If the ``bundle_or_obj`` argument is not provided, it builds the URI
        for the list endpoint.

        If the ``bundle_or_obj`` argument is provided, it builds the URI for
        the detail endpoint.

        Return the generated URI. If that URI can not be reversed (not found
        in the URLconf), it will return an empty string.
        """
         #check for format
        if isinstance(bundle_or_obj,Bundle):
            _format = self.determine_format(bundle_or_obj.request)
        ##strip the "application" in "application/{format}"
            _format = _format.split('/')[1]

        ##WARNING: if a method is not provided for your type will pass to default<
            method = getattr(self, '%s_%s' % ('get_resource_uri', _format), self.get_resource_uri_default)
            return method(bundle_or_obj, **kwargs)
        else:
            return self.get_resource_uri_default(bundle_or_obj, **kwargs)


    def get_resource_uri_default(self, bundle_or_obj, url_name='api_dispatch_list', **kwargs):
        if bundle_or_obj is not None:
            url_name = 'api_dispatch_detail'

        try:
            return self._build_reverse_url(url_name, kwargs=self.resource_uri_kwargs(bundle_or_obj))
        except NoReverseMatch:
            return ''

    def get_via_uri(self, uri, request=None):
        """
        This pulls apart the salient bits of the URI and populates the
        resource via a ``obj_get``.

        Optionally accepts a ``request``.

        If you need custom behavior based on other portions of the URI,
        simply override this method.
        """
        method = getattr(self, '%s_%s' % ('get_via_uri', get_request_class(request)))
        return method(uri, request)


    def get_via_uri_wsgirequest(self, uri, request=None):
        prefix = get_script_prefix()
        chomped_uri = uri

        if prefix and chomped_uri.startswith(prefix):
            chomped_uri = chomped_uri[len(prefix)-1:]
        try:
            view, view_args, view_kwargs = resolve(chomped_uri)
            if self.parent_obj:
                #am being used as a sub resource. Need to resolve correctly
                rest_of_url = view_kwargs.pop('%s_rest_of_url'%self.parent_resource._meta.resource_name)
                resolver = CustomRegexURLResolver(RegexPattern(r'^'), self.urls)
                if rest_of_url[-1] != '/':
                    rest_of_url = "%s%s" %(rest_of_url, trailing_slash())
                view, view_args, view_kwargs = resolver.resolve(rest_of_url)
        except Resolver404:
            raise NotFound("The URL provided '%s' was not a link to a valid resource." % uri)

        bundle = self.build_bundle(request=request)
        return self.obj_get(bundle=bundle, **self.remove_api_resource_names(view_kwargs))

    # Data preparation.
    def full_dehydrate(self, bundle, for_list=False):
        """
        Given a bundle with an object instance, extract the information from it
        to populate the resource.
        """
        use_in = ['all', 'list' if for_list else 'detail']

        # Dehydrate each field.
        for field_name, field_object in list(self.fields.items()):
            # If it's not for use in this mode, skip
            field_use_in = getattr(field_object, 'use_in', 'all')
            if callable(field_use_in):
                if not field_use_in(bundle,for_list):
                    continue
            else:
                if field_use_in not in use_in:
                    continue
            '''
            # A touch leaky but it makes URI resolution work.
            if getattr(field_object, 'dehydrated_type', None) == 'related':
                field_object.api_name = self._meta.api_name
                field_object.resource_name = self._meta.resource_name
                field_object.resource_obj = self
            '''
            bundle.data[field_name] = field_object.dehydrate(bundle, for_list=for_list)

            # Check for an optional method to do further dehydration.
            method = getattr(self, "dehydrate_%s" % field_name, None)

            if method:
                bundle.data[field_name] = method(bundle)

        bundle = self.dehydrate(bundle)
        return bundle

    def dehydrate(self, bundle):
        """
        A hook to allow a final manipulation of data once all fields/methods
        have built out the dehydrated data.

        Useful if you need to access more than one dehydrated field or want
        to annotate on additional data.

        Must return the modified bundle.
        """
        return bundle

    def full_hydrate(self, bundle):
        """
        Given a populated bundle, distill it and turn it back into
        a full-fledged object instance.
        """
        if bundle.obj is None:
            bundle.obj = self._meta.object_class()

        bundle = self.hydrate(bundle)

        for field_name, field_object in list(self.fields.items()):
            if field_object.readonly is True:
                continue

            # Check for an optional method to do further hydration.
            method = getattr(self, "hydrate_%s" % field_name, None)

            if method:
                bundle = method(bundle)

            if field_object.attribute:
                value = field_object.hydrate(bundle)

                # NOTE: We only get back a bundle when it is related field.
                if isinstance(value, Bundle) and value.errors.get(field_name):
                    bundle.errors[field_name] = value.errors[field_name]

                if value is not None or field_object.null:
                    # We need to avoid populating M2M data here as that will
                    # cause things to blow up.
                    if not getattr(field_object, 'is_related', False):
                        setattr(bundle.obj, field_object.attribute, value)
                    elif not getattr(field_object, 'is_m2m', False):
                        '''
                        Changed the order of the follwing elif conditions to allow a fk field that can be blank to be set to a null value
                        '''
                        if value is not None:
                            # NOTE: A bug fix in Django (ticket #18153) fixes incorrect behavior
                            # which Tastypie was relying on.  To fix this, we store value.obj to
                            # be saved later in save_related.
                            try:
                                setattr(bundle.obj, field_object.attribute, value.obj)
                            except (ValueError, ObjectDoesNotExist):
                                bundle.related_objects_to_save[field_object.attribute] = value.obj
                        elif field_object.blank:
                            continue
                        elif field_object.null:
                            setattr(bundle.obj, field_object.attribute, value)

        bundle = self.hydrate_m2m(bundle)
        return bundle

    def hydrate(self, bundle):
        """
        A hook to allow an initial manipulation of data before all methods/fields
        have built out the hydrated data.

        Useful if you need to access more than one hydrated field or want
        to annotate on additional data.

        Must return the modified bundle.
        """
        return bundle

    def hydrate_m2m(self, bundle):
        """
        Populate the ManyToMany data on the instance.
        """

        if bundle.obj is None:
            raise HydrationError("You must call 'full_hydrate' before attempting to run 'hydrate_m2m' on %r." % self)

        for field_name, field_object in list(self.fields.items()):
            if not getattr(field_object, 'is_m2m', False):
                continue

            if isinstance(field_object, fields.BaseSubResourceField) and\
                    bundle.obj.id:
                #no hydraiton for subresources for edit
                continue

            if field_object.attribute:
                # Note that we only hydrate the data, leaving the instance
                # unmodified. It's up to the user's code to handle this.
                # The ``ModelResource`` provides a working baseline
                # in this regard.
                value = field_object.hydrate_m2m(bundle)
                if not (value is None and field_object.readonly):
                    bundle.data[field_name] = value

        for field_name, field_object in list(self.fields.items()):
            if not getattr(field_object, 'is_m2m', False):
                continue

            if isinstance(field_object, fields.BaseSubResourceField) and\
                    bundle.obj.id:
                    #no hydraiton for subresources for edit
                continue
            method = getattr(self, "hydrate_%s" % field_name, None)

            if method:
                method(bundle)

        return bundle

    def build_schema(self):
        """
        Returns a dictionary of all the fields on the resource and some
        properties about those fields.

        Used by the ``schema/`` endpoint to describe what will be available.
        """
        data = {
            'fields': {},
            'default_format': self._meta.default_format,
            'allowed_list_http_methods': self._meta.list_allowed_methods,
            'allowed_detail_http_methods': self._meta.detail_allowed_methods,
            'default_limit': self._meta.limit,
        }

        if self._meta.ordering:
            data['ordering'] = self._meta.ordering

        if self._meta.filtering:
            data['filtering'] = self._meta.filtering

        for field_name, field_object in list(self.fields.items()):
            data['fields'][field_name] = field_object.build_schema(field_name=field_name,resource_uri=self.get_resource_uri(), resource=self)
        return data

    def dehydrate_resource_uri(self, bundle):
        """
        For the automatically included ``resource_uri`` field, dehydrate
        the URI for the given bundle.

        Returns empty string if no URI can be generated.
        """
        try:
            return self.get_resource_uri(bundle)
        except NotImplementedError:
            return ''
        except NoReverseMatch:
            return ''

    def generate_cache_key(self, *args, **kwargs):
        """
        Creates a unique-enough cache key.

        This is based off the current api_name/resource_name/args/kwargs.
        """
        smooshed = []

        for key, value in list(kwargs.items()):
            smooshed.append("%s=%s" % (key, value))

        # Use a list plus a ``.join()`` because it's faster than concatenation.
        return "%s:%s:%s:%s" % (self._meta.api_name, self._meta.resource_name, ':'.join(args), ':'.join(sorted(smooshed)))

    # Data access methods.

    def get_object_list(self, request):
        """
        A hook to allow making returning the list of available objects.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def apply_authorization_limits(self, request, object_list):
        """
        Deprecated.

        FIXME: REMOVE BEFORE 1.0
        """
        return self._meta.authorization.apply_limits(request, object_list)

    def can_create(self):
        """
        Checks to ensure ``post`` is within ``allowed_methods``.
        """
        allowed = set(self._meta.list_allowed_methods + self._meta.detail_allowed_methods)
        return 'post' in allowed

    def can_update(self):
        """
        Checks to ensure ``put`` is within ``allowed_methods``.

        Used when hydrating related data.
        """
        allowed = set(self._meta.list_allowed_methods + self._meta.detail_allowed_methods)
        return 'put' in allowed

    def can_delete(self):
        """
        Checks to ensure ``delete`` is within ``allowed_methods``.
        """
        allowed = set(self._meta.list_allowed_methods + self._meta.detail_allowed_methods)
        return 'delete' in allowed

    def apply_filters(self, request, applicable_filters):
        """
        A hook to alter how the filters are applied to the object list.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def obj_get_list(self, bundle, **kwargs):
        """
        Fetches the list of objects available on the resource.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def cached_obj_get_list(self, bundle, **kwargs):
        """
        A version of ``obj_get_list`` that uses the cache as a means to get
        commonly-accessed data faster.
        """
        cache_key = self.generate_cache_key('list', **kwargs)
        obj_list = self._meta.cache.get(cache_key)

        if obj_list is None:
            obj_list = self.obj_get_list(bundle=bundle, **kwargs)
            self._meta.cache.set(cache_key, obj_list)

        return obj_list

    def obj_get(self, bundle, **kwargs):
        """
        Fetches an individual object on the resource.

        This needs to be implemented at the user level. If the object can not
        be found, this should raise a ``NotFound`` exception.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def cached_obj_get(self, bundle, **kwargs):
        """
        A version of ``obj_get`` that uses the cache as a means to get
        commonly-accessed data faster.
        """
        optimize_query = kwargs.pop('_optimize_query',False)

        cache_key = self.generate_cache_key('detail', **kwargs)
        cached_bundle = self._meta.cache.get(cache_key)

        if cached_bundle is None:
            cached_bundle = self.obj_get(bundle=bundle, _optimize_query=optimize_query, **kwargs)
            self._meta.cache.set(cache_key, cached_bundle)

        return cached_bundle

    def obj_create(self, bundle, **kwargs):
        """
        Creates a new object based on the provided data.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def obj_update(self, bundle, **kwargs):
        """
        Updates an existing object (or creates a new object) based on the
        provided data.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def obj_delete_list(self, bundle, **kwargs):
        """
        Deletes an entire list of objects.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def obj_delete_list_for_update(self, bundle, **kwargs):
        """
        Deletes an entire list of objects, specific to PUT list.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def obj_delete(self, bundle, **kwargs):
        """
        Deletes a single object.

        This needs to be implemented at the user level.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    def create_response(self, request, data, response_class=None, **response_kwargs):
        """
        Extracts the common "which-format/serialize/return-response" cycle.

        Mostly a useful shortcut/hook.
        """
        response_class = response_class or  self._meta.response_router_obj[request].get_default_response_class()
        desired_format = self.determine_format(request)
        serialized = self.serialize(request, data, desired_format)
        return response_class(content=serialized,
                              content_type=build_content_type(desired_format), **response_kwargs)


    def error_response(self, request, errors, response_class=None):
        """
        Extracts the common "which-format/serialize/return-error-response"
        cycle.

        Should be used as much as possible to return errors.
        """
        if response_class is None:
            response_class = self._meta.response_router_obj[request].get_bad_request_response_class()

        desired_format = None

        if request:
            if request.GET.get('callback', None) is None:
                try:
                    desired_format = self.determine_format(request)
                except BadRequest:
                    pass  # Fall through to default handler below
            else:
                # JSONP can cause extra breakage.
                desired_format = 'application/json'

        if not desired_format:
            desired_format = self._meta.default_format

        try:
            serialized = self.serialize(request, errors, desired_format)
        except BadRequest as e:
            error = "Additional errors occurred, but serialization of those errors failed."

            if settings.DEBUG:
                error += " %s" % e

            return response_class(content=error, content_type='text/plain')

        return response_class(content=serialized, content_type=build_content_type(desired_format))

    def validate_to_one_subresource(self, bundle):
        if self.parent_obj and self.parent_resource and\
           isinstance(self.parent_resource.fields[self.parent_field], fields.ToOneSubResourceField):
            try:
                getattr(self.parent_obj, self.parent_resource.fields[self.parent_field].attribute)
                #if exists then it shud be 400
                raise ImmediateResponse(response=self.error_response(bundle.request, {"error_message":"'%s' already exists for this parent."%(self.parent_field )}))
            except ObjectDoesNotExist:
                pass
        return {}

    def is_valid(self, bundle):
        """
        Handles checking if the data provided by the user is valid.

        Mostly a hook, this uses class assigned to ``validation`` from
        ``Resource._meta``.

        If validation fails, an error is raised with the error messages
        serialized inside it.
        """

        def get_related_bundle(related_resource, value, bundle):
            if isinstance(value, Bundle):
                return value
            else:
                data = value
                if isinstance(data, basestring):
                    #happens incase of a toonefield
                    data = {'resource_uri':data}
                return related_resource.build_bundle(obj=None, data=data,
                    request=bundle.request)

        errors = self._meta.validation.is_valid(bundle, bundle.request) or {}

        for field_name, field_object in list(self.fields.items()):
            if not getattr(field_object, 'is_related', False):
                #if its not a to one field or a m2m field or a subresource
                continue

            if field_object.readonly:
                continue

            if not field_object.attribute:
                continue

            if field_object.blank and (field_name not in bundle.data or bundle.data.get(field_name) is None):
                continue


            related_resource = field_object.get_related_resource(bundle.obj, bundle)
            if not related_resource._meta.create_on_related_fields:
                continue

            if isinstance(field_object, fields.BaseSubResourceField) and\
                    bundle.obj.id:
                #no validation for subresources for edit
                continue


            if getattr(field_object, 'is_m2m', False):
                for data in bundle.data.get(field_name,[]):
                    related_bundle = get_related_bundle(related_resource, data, bundle)
                    related_bundle_valid = related_resource.is_valid(related_bundle)
                    if not related_bundle_valid:
                        errors.get(field_name,[]).append(related_bundle.errors)
            else:
                #m2m field
                related_bundle = get_related_bundle(related_resource, bundle.data.get(field_name,{}), bundle)
                related_bundle_valid = related_resource.is_valid(related_bundle)
                if not related_bundle_valid:
                    errors[field_name] = related_bundle.errors

        if errors:
            bundle.errors = errors
            return False

        return True

    def rollback(self, bundles):
        """
        Given the list of bundles, delete all objects pertaining to those
        bundles.

        This needs to be implemented at the user level. No exceptions should
        be raised if possible.

        ``ModelResource`` includes a full working version specific to Django's
        ``Models``.
        """
        raise NotImplementedError()

    # Views.

    def get_list(self, request, **kwargs):
        """
        Returns a serialized list of resources.

        Calls ``obj_get_list`` to provide the data, then handles that result
        set and serializes it.

        Should return a HttpResponse (200 OK).
        """
        # TODO: Uncached for now. Invalidation that works for everyone may be
        #       impossible.
        base_bundle = self.build_bundle(request=request)
        objects = self.obj_get_list(bundle=base_bundle, **self.remove_api_resource_names(kwargs))

        try:
            sorted_objects = self.apply_sorting(objects, options=request.GET)
        except (InvalidSortError) as e:
            data = {"error": e.message}
            return self.error_response(request, data, response_class=self._meta.response_router_obj[request].get_bad_request_response_class())

        to_be_serialized = self.paginate(base_bundle, sorted_objects)

        base_bundle = self.preprocess('read_list', base_bundle)

        # Dehydrate the bundles in preparation for serialization.
        bundles = []
        for obj in to_be_serialized[self._meta.collection_name]:
            bundle = self.build_bundle(obj=obj, request=request)
            bundles.append(self.full_dehydrate(bundle, for_list=True))

        to_be_serialized[self._meta.collection_name] = bundles
        to_be_serialized = self.alter_list_data_to_serialize(request, to_be_serialized)
        self.fire_event('list_read', args=([bundle.obj for obj in \
                to_be_serialized[self._meta.collection_name]], base_bundle))

        return self.create_response(request, to_be_serialized)

    def get_detail(self, request, **kwargs):
        """
        Returns a single serialized resource.

        Calls ``cached_obj_get/obj_get`` to provide the data, then handles that result
        set and serializes it.

        Should return a HttpResponse (200 OK).
        """
        basic_bundle = self.build_bundle(request=request)

        try:
            obj = self.cached_obj_get(bundle=basic_bundle, _optimize_query=True, **self.remove_api_resource_names(kwargs))
        except ObjectDoesNotExist:
            return self._meta.response_router_obj[request].get_not_found_response()
        except MultipleObjectsReturned:
            return  self._meta.response_router_obj[request].get_multiple_choices_response("More than one resource is found at this URI.")

        bundle = self.build_bundle(obj=obj, request=request)
        bundle = self.preprocess('read_detail', bundle)
        bundle = self.full_dehydrate(bundle)
        bundle = self.alter_detail_data_to_serialize(request, bundle)
        self.fire_event('detail_read', args=(self.get_object_list(bundle.request), bundle))
        return self.create_response(request, bundle)

    def post_list(self, request, **kwargs):
        """
        Creates a new resource/object with the provided data.

        Calls ``obj_create`` with the provided data and returns a response
        with the new resource's location.

        If a new resource is created, return ``HttpCreated`` (201 Created).
        If ``Meta.always_return_data = True``, there will be a populated body
        of serialized data.
        """
        deserialized = self.deserialize(request, request.body, format=request.META.get('CONTENT_TYPE', 'application/json'))
        deserialized = self.alter_deserialized_detail_data(request, deserialized)
        bundle = self.build_bundle(data=dict_strip_unicode_keys(deserialized), request=request)

        updated_bundle = self.obj_create(bundle, **self.remove_api_resource_names(kwargs))
        location = self.get_resource_uri(updated_bundle)

        response_class = self._meta.response_router_obj[request].get_created_response_class()
        if not self._meta.always_return_data:
            return response_class(location=location)
        else:
            updated_bundle.data = {}
            updated_bundle = self.full_dehydrate(updated_bundle)
            updated_bundle = self.alter_detail_data_to_serialize(request, updated_bundle)
            return self.create_response(request, updated_bundle, response_class=response_class, location=location)

    def post_detail(self, request, **kwargs):
        """
        Creates a new subcollection of the resource under a resource.

        This is not implemented by default because most people's data models
        aren't self-referential.

        If a new resource is created, return ``HttpCreated`` (201 Created).
        """
        return  self._meta.response_router_obj[request].get_not_implemented_response()

    def put_list(self, request, **kwargs):
        """
        Replaces a collection of resources with another collection.

        Calls ``delete_list`` to clear out the collection then ``obj_create``
        with the provided the data to create the new collection.

        Return ``HttpNoContent`` (204 No Content) if
        ``Meta.always_return_data = False`` (default).

        Return ``HttpAccepted`` (200 OK) if
        ``Meta.always_return_data = True``.
        """
        deserialized = self.deserialize(request, request.body, format=request.META.get('CONTENT_TYPE', 'application/json'))
        deserialized = self.alter_deserialized_list_data(request, deserialized)

        if not self._meta.collection_name in deserialized:
            raise BadRequest("Invalid data sent.")

        basic_bundle = self.build_bundle(request=request)
        self.obj_delete_list_for_update(bundle=basic_bundle, **self.remove_api_resource_names(kwargs))
        bundles_seen = []

        for object_data in deserialized[self._meta.collection_name]:
            bundle = self.build_bundle(data=dict_strip_unicode_keys(object_data), request=request)

            # Attempt to be transactional, deleting any previously created
            # objects if validation fails.
            try:
                self.obj_create(bundle=bundle, **self.remove_api_resource_names(kwargs))
                bundles_seen.append(bundle)
            except ImmediateResponse:
                self.rollback(bundles_seen)
                raise

        if not self._meta.always_return_data:
            return  self._meta.response_router_obj[request].get_no_content_response()
        else:
            to_be_serialized = {}
            to_be_serialized[self._meta.collection_name] = [self.full_dehydrate(bundle, for_list=True) for bundle in bundles_seen]
            to_be_serialized = self.alter_list_data_to_serialize(request, to_be_serialized)
            response_class =  self._meta.response_router_obj[request].get_accepted_response_class()
            return self.create_response(request, to_be_serialized, response_class=response_class)

    def put_detail(self, request, **kwargs):
        """
        Either updates an existing resource or creates a new one with the
        provided data.

        Calls ``obj_update`` with the provided data first, but falls back to
        ``obj_create`` if the object does not already exist.

        If a new resource is created, return ``HttpCreated`` (201 Created).
        If ``Meta.always_return_data = True``, there will be a populated body
        of serialized data.

        If an existing resource is modified and
        ``Meta.always_return_data = False`` (default), return ``HttpNoContent``
        (204 No Content).
        If an existing resource is modified and
        ``Meta.always_return_data = True``, return ``HttpAccepted`` (200
        OK).
        """
        deserialized = self.deserialize(request, request.body, format=request.META.get('CONTENT_TYPE', 'application/json'))
        deserialized = self.alter_deserialized_detail_data(request, deserialized)
        bundle = self.build_bundle(data=dict_strip_unicode_keys(deserialized), request=request)

        try:
            updated_bundle = self.obj_update(bundle=bundle, **self.remove_api_resource_names(kwargs))

            if not self._meta.always_return_data:
                return self.get_no_content_response(request)
            else:
                updated_bundle = self.full_dehydrate(updated_bundle)
                updated_bundle = self.alter_detail_data_to_serialize(request, updated_bundle)
                response_class = self._meta.response_router_obj[request].get_accepted_response_class()
                return self.create_response(request, updated_bundle, response_class=response_class)
        except (NotFound, MultipleObjectsReturned):
            updated_bundle = self.obj_create(bundle=bundle, **self.remove_api_resource_names(kwargs))
            location = self.get_resource_uri(updated_bundle)

            if not self._meta.always_return_data:
                return  self._meta.response_router_obj[request].get_created_response(location=location)
            else:
                updated_bundle = self.full_dehydrate(updated_bundle)
                updated_bundle = self.alter_detail_data_to_serialize(request, updated_bundle)
                response_class =  self._meta.response_router_obj[request].get_created_response_class()
                return self.create_response(request, updated_bundle, response_class=response_class, location=location)

    def delete_list(self, request, **kwargs):
        """
        Destroys a collection of resources/objects.

        Calls ``obj_delete_list``.

        If the resources are deleted, return ``HttpNoContent`` (204 No Content).
        """
        bundle = self.build_bundle(request=request)
        self.obj_delete_list(bundle=bundle, request=request, **self.remove_api_resource_names(kwargs))
        return  self._meta.response_router_obj[request].get_no_content_response()

    def delete_detail(self, request, **kwargs):
        """
        Destroys a single resource/object.

        Calls ``obj_delete``.

        If the resource is deleted, return ``HttpNoContent`` (204 No Content).
        If the resource did not exist, return ``Http404`` (404 Not Found).
        """
        # Manually construct the bundle here, since we don't want to try to
        # delete an empty instance.
        bundle = self.build_bundle(request=request)
        bundle.obj = None
        #bundle = Bundle(request=request)
        try:
            self.obj_delete(bundle=bundle, **self.remove_api_resource_names(kwargs))
            return  self._meta.response_router_obj[request].get_no_content_response()
        except NotFound:
            return self._meta.response_router_obj[request].get_not_found_response()

    def patch_list(self, request, **kwargs):
        """
        Updates a collection in-place.

        The exact behavior of ``PATCH`` to a list resource is still the matter of
        some debate in REST circles, and the ``PATCH`` RFC isn't standard. So the
        behavior this method implements (described below) is something of a
        stab in the dark. It's mostly cribbed from GData, with a smattering
        of ActiveResource-isms and maybe even an original idea or two.

        The ``PATCH`` format is one that's similar to the response returned from
        a ``GET`` on a list resource::

            {
              "objects": [{object}, {object}, ...],
              "deleted_objects": ["URI", "URI", "URI", ...],
            }

        For each object in ``objects``:

            * If the dict does not have a ``resource_uri`` key then the item is
              considered "new" and is handled like a ``POST`` to the resource list.

            * If the dict has a ``resource_uri`` key and the ``resource_uri`` refers
              to an existing resource then the item is a update; it's treated
              like a ``PATCH`` to the corresponding resource detail.

            * If the dict has a ``resource_uri`` but the resource *doesn't* exist,
              then this is considered to be a create-via-``PUT``.

        Each entry in ``deleted_objects`` referes to a resource URI of an existing
        resource to be deleted; each is handled like a ``DELETE`` to the relevent
        resource.

        In any case:

            * If there's a resource URI it *must* refer to a resource of this
              type. It's an error to include a URI of a different resource.

            * ``PATCH`` is all or nothing. If a single sub-operation fails, the
              entire request will fail and all resources will be rolled back.

          * For ``PATCH`` to work, you **must** have ``put`` in your
            :ref:`detail-allowed-methods` setting.

          * To delete objects via ``deleted_objects`` in a ``PATCH`` request you
            **must** have ``delete`` in your :ref:`detail-allowed-methods`
            setting.

        Substitute appropriate names for ``objects`` and
        ``deleted_objects`` if ``Meta.collection_name`` is set to something
        other than ``objects`` (default).
        """
        request = convert_post_to_patch(request)
        deserialized = self.deserialize(request, request.body, format=request.META.get('CONTENT_TYPE', 'application/json'))

        collection_name = self._meta.collection_name
        deleted_collection_name = 'deleted_%s' % collection_name
        if collection_name not in deserialized:
            raise BadRequest("Invalid data sent: missing '%s'" % collection_name)

        if len(deserialized[collection_name]) and 'patch' not in self._meta.detail_allowed_methods:
            raise ImmediateResponse(response= self._meta.response_router_obj[request].get_method_notallowed_response('patch'))

        deleted_collection = deserialized.get(deleted_collection_name, [])

        if deleted_collection:
            if 'delete' not in self._meta.detail_allowed_methods:
                raise ImmediateResponse(response= self._meta.response_router_obj[request].get_method_notallowed_response('delete'))
            to_be_deleted = []

            for thing in deleted_collection:
                try:
                    if isinstance(thing, basestring):
                        obj = self.get_via_uri(thing, request=request)
                    elif isinstance(thing, dict) and 'resource_uri' in thing:
                        uri = thing.pop('resource_uri')
                        obj = self.get_via_uri(uri, request=request)
                    else:
                        raise ValueError("cannot resolve %s into a valid object for deletions" % thing)
                    bundle = self.build_bundle(obj=obj, request=request)
                    to_be_deleted.append(bundle)
                except ObjectDoesNotExist:
                    raise ImmediateResponse(response=self._meta.response_router_obj[request].get_response_notfound_class()("Couldn't find instace for data: %s" % thing))
                except MultipleObjectsReturned:
                    raise ImmediateResponse(response=self._meta.response_router_obj[request].get_bad_request_response_class()("Couldn't find instace for data: %s" % thing))
            for del_bundle in to_be_deleted:
                self.obj_delete(bundle=del_bundle)

        to_be_updated, to_be_created, bundles_seen = [], [], []
        for data in deserialized[collection_name]:
            # If there's a resource_uri then this is either an
            # update-in-place or a create-via-PUT.
            if "resource_uri" in data:
                uri = data.pop('resource_uri')
                try:
                    obj = self.get_via_uri(uri, request=request)

                    # The object does exist, so this is an update-in-place.
                    bundle = self.build_bundle(obj=obj, request=request)
                    bundle = self.full_dehydrate(bundle, for_list=False)
                    bundle = self.alter_detail_data_to_serialize(request, bundle)
                    self.authorized_update_detail(self.get_object_list(bundle.request), bundle)
                    bundle.new_data = data
                    self.is_valid(bundle)
                    to_be_updated.append((request, bundle, data))
                except ObjectDoesNotExist:
                    raise ImmediateResponse(response=self._meta.response_router_obj[request].get_response_notfound_class()("Couldn't find instace for uri: %s" % uri))
                except MultipleObjectsReturned:
                    raise ImmediateResponse(response=self._meta.response_router_obj[request].get_bad_request_response_class()("Couldn't find instace for uri: %s" % uri))

                bundles_seen.append(bundle)
            else:
                data = self.alter_deserialized_detail_data(request, data)
                bundle = self.build_bundle(data=dict_strip_unicode_keys(data), request=request)
                to_be_created.append(bundle)

        for cr_bun in to_be_created:
            self.obj_create(bundle=cr_bun)
            bundles_seen.append(cr_bun)

        for up_agrs in to_be_updated:
            self.update_in_place(*up_agrs)

        self.fire_event('list_updated', args=(self.get_object_list(request), self.build_bundle(request=request)))
        response_class = self._meta.response_router_obj[request].get_accepted_response_class()
        if not self._meta.always_return_data:
            return response_class()
        else:
            to_be_serialized = {}
            to_be_serialized['objects'] = [self.full_dehydrate(bundle, for_list=True) for bundle in bundles_seen]
            to_be_serialized = self.alter_list_data_to_serialize(request, to_be_serialized)
            return self.create_response(request, to_be_serialized, response_class=response_class)

    def patch_detail(self, request, **kwargs):
        """
        Updates a resource in-place.

        Calls ``obj_update``.

        If the resource is updated, return ``HttpAccepted`` (202 Accepted).
        If the resource did not exist, return ``HttpNotFound`` (404 Not Found).
        """
        request = convert_post_to_patch(request)
        basic_bundle = self.build_bundle(request=request)
        # We want to be able to validate the update, but we can't just pass
        # the partial data into the validator since all data needs to be
        # present. Instead, we basically simulate a PUT by pulling out the
        # original data and updating it in-place.
        # So first pull out the original object. This is essentially
        # ``get_detail``.
        try:
            obj = self.cached_obj_get(bundle=basic_bundle, _optimize_query=True, **self.remove_api_resource_names(kwargs))
        except ObjectDoesNotExist:
            return  self._meta.response_router_obj[request].get_not_found_response()
        except MultipleObjectsReturned:
            content = "More than one resource is found at this URI."
            return  self._meta.response_router_obj[request].get_multiple_choices_response(content)

        bundle = self.build_bundle(obj=obj, request=request)
        bundle = self.full_dehydrate(bundle)
        bundle = self.alter_detail_data_to_serialize(request, bundle)

        # Now update the bundle in-place.
        deserialized = self.deserialize(request, request.body, format=request.META.get('CONTENT_TYPE', 'application/json'))
        self.update_in_place(request, bundle, deserialized)

        if not self._meta.always_return_data:
            return  self._meta.response_router_obj[request].get_accepted_response_class()()
        else:
            bundle = self.full_dehydrate(bundle)
            bundle = self.alter_detail_data_to_serialize(request, bundle)
            response_class =  self._meta.response_router_obj[request].get_accepted_response_class()
            return self.create_response(request, bundle, response_class=response_class)

    def update_in_place(self, request, original_bundle, new_data):
        """
        Update the object in original_bundle in-place using new_data.
        """
        if hasattr(original_bundle.obj,'_prefetched_objects_cache'):
            for key in list(new_data.keys()):
                if key in self._meta.prefetch_related:
                    field = self.fields.get(key)
                    try:
                        cache_key = getattr(original_bundle.obj,field.attribute).prefetch_cache_name
                        original_bundle.obj._prefetched_objects_cache.pop(cache_key,None)
                    except AttributeError:
                        pass

        original_bundle.original_data = original_bundle.data.copy()
        original_bundle.data.update(**dict_strip_unicode_keys(new_data))
        original_bundle.new_data = new_data

        # Now we've got a bundle with the new data sitting in it and we're
        # we're basically in the same spot as a PUT request. SO the rest of this
        # function is cribbed from put_detail.
        self.alter_deserialized_detail_data(request, original_bundle.data)
        kwargs = {
            self._meta.detail_uri_name: self.get_bundle_detail_data(original_bundle),
            'request': request,
        }
        return self.obj_update(bundle=original_bundle, **kwargs)

    def get_schema(self, request, **kwargs):
        """
        Returns a serialized form of the schema of the resource.

        Calls ``build_schema`` to generate the data. This method only responds
        to HTTP GET.

        Should return a HttpResponse (200 OK).
        """
        self.method_check(request, allowed=['get'])
        self.is_authenticated(request)
        self.throttle_check(request)
        self.log_throttled_access(request)
        bundle = self.build_bundle(request=request)
        #Cant imagine why schema has to be validated!
        #self.authorized_read_detail(self.get_object_list(bundle.request), bundle)
        return self.create_response(request, self.build_schema())

    def get_multiple(self, request, **kwargs):
        """
        Returns a serialized list of resources based on the identifiers
        from the URL.

        Calls ``obj_get`` to fetch only the objects requested. This method
        only responds to HTTP GET.

        Should return a HttpResponse (200 OK).
        """
        self.method_check(request, allowed=['get'])
        self.is_authenticated(request)
        self.throttle_check(request)

        # Rip apart the list then iterate.
        kwarg_name = '%s_list' % self._meta.detail_uri_name
        obj_identifiers = kwargs.get(kwarg_name, '').split(';')
        objects = []
        not_found = []
        base_bundle = self.build_bundle(request=request)

        for identifier in obj_identifiers:
            try:
                obj = self.obj_get(bundle=base_bundle, _optimize_query=True, **{self._meta.detail_uri_name: identifier})
                bundle = self.build_bundle(obj=obj, request=request)
                bundle = self.full_dehydrate(bundle, for_list=True)
                objects.append(bundle)
            except (ObjectDoesNotExist, Unauthorized):
                not_found.append(identifier)

        object_list = {
            self._meta.collection_name: objects,
        }

        if len(not_found):
            object_list['not_found'] = not_found

        self.log_throttled_access(request)
        return self.create_response(request, object_list)


class ModelDeclarativeMetaclass(DeclarativeMetaclass):
    def __new__(cls, name, bases, attrs):
        meta = attrs.get('Meta')

        if meta and hasattr(meta, 'queryset'):
            setattr(meta, 'object_class', meta.queryset.model)

        new_class = super(ModelDeclarativeMetaclass, cls).__new__(cls, name, bases, attrs)
        include_fields = getattr(new_class._meta, 'fields', [])
        excludes = getattr(new_class._meta, 'excludes', [])
        field_names = list(new_class.base_fields.keys())

        for field_name in field_names:
            if field_name == 'resource_uri':
                continue
            if field_name in new_class.declared_fields:
                continue
            if len(include_fields) and not field_name in include_fields:
                del(new_class.base_fields[field_name])
            if len(excludes) and field_name in excludes:
                del(new_class.base_fields[field_name])

        # Add in the new fields.
        new_class.base_fields.update(new_class.get_fields(include_fields, excludes))

        if getattr(new_class._meta, 'include_absolute_url', True):
            if not 'absolute_url' in new_class.base_fields:
                new_class.base_fields['absolute_url'] = fields.CharField(attribute='get_absolute_url', readonly=True)
        elif 'absolute_url' in new_class.base_fields and not 'absolute_url' in attrs:
            del(new_class.base_fields['absolute_url'])

        return new_class


class BaseModelResource(Resource):
    """
    A subclass of ``Resource`` designed to work with Django's ``Models``.

    This class will introspect a given ``Model`` and build a field list based
    on the fields found on the model (excluding relational fields).

    Given that it is aware of Django's ORM, it also handles the CRUD data
    operations of the resource.
    """
    @classmethod
    def should_skip_field(cls, field):
        """
        Given a Django model field, return if it should be included in the
        contributed ApiFields.
        """
        # Ignore certain fields (related fields).
        if getattr(field, 'rel', None):
            return True

        if getattr(field, 'remote_field'):
            return True

        return False

    @classmethod
    def api_field_from_django_field(cls, f, default=fields.CharField):
        """
        Returns the field type that would likely be associated with each
        Django type.
        """
        result = default
        internal_type = f.get_internal_type()

        if internal_type in ('DateField', 'DateTimeField'):
            result = fields.DateTimeField
        elif internal_type in ('BooleanField', 'NullBooleanField'):
            result = fields.BooleanField
        elif internal_type in ('FloatField',):
            result = fields.FloatField
        elif internal_type in ('DecimalField',):
            result = fields.DecimalField
        elif internal_type in ('IntegerField', 'PositiveIntegerField', 'PositiveSmallIntegerField', 'SmallIntegerField', 'AutoField'):
            result = fields.IntegerField
        elif internal_type in ('FileField', 'ImageField'):
            result = fields.FileField
        elif internal_type == 'TimeField':
            result = fields.TimeField
        # TODO: Perhaps enable these via introspection. The reason they're not enabled
        #       by default is the very different ``__init__`` they have over
        #       the other fields.
        # elif internal_type == 'ForeignKey':
        #     result = ForeignKey
        # elif internal_type == 'ManyToManyField':
        #     result = ManyToManyField

        return result

    @classmethod
    def get_fields(cls, fields=None, excludes=None):
        """
        Given any explicit fields to include and fields to exclude, add
        additional fields based on the associated model.
        """
        final_fields = {}
        fields = fields or []
        excludes = excludes or []

        if not cls._meta.object_class:
            return final_fields

        for f in cls._meta.object_class._meta.fields:
            # If the field name is already present, skip
            if f.name in cls.base_fields:
                continue

            # If field is not present in explicit field listing, skip
            if fields and f.name not in fields:
                continue

            # If field is in exclude list, skip
            if excludes and f.name in excludes:
                continue

            if cls.should_skip_field(f):
                continue

            api_field_class = cls.api_field_from_django_field(f)

            kwargs = {
                'attribute': f.name,
                'help_text': f.help_text,
            }

            if f.null is True:
                kwargs['null'] = True

            kwargs['unique'] = f.unique

            if not f.null and f.blank is True:
                kwargs['default'] = ''
                kwargs['blank'] = True

            if f.get_internal_type() == 'TextField':
                kwargs['default'] = ''

            if f.has_default():
                kwargs['default'] = f.default

            if getattr(f, 'auto_now', False):
                kwargs['default'] = f.auto_now

            if getattr(f, 'auto_now_add', False):
                kwargs['default'] = f.auto_now_add

            final_fields[f.name] = api_field_class(**kwargs)
            final_fields[f.name].instance_name = f.name

        return final_fields

    def check_filtering(self, field_name, filter_type='exact', filter_bits=None):
        """
        Given a field name, a optional filter type and an optional list of
        additional relations, determine if a field can be filtered on.

        If a filter does not meet the needed conditions, it should raise an
        ``InvalidFilterError``.

        If the filter meets the conditions, a list of attribute names (not
        field names) will be returned.
        """
        if filter_bits is None:
            filter_bits = []

        if not field_name in self._meta.filtering:
            raise InvalidFilterError("The '%s' field does not allow filtering." % field_name)

        # Check to see if it's an allowed lookup type.
        if filter_type != "exact" and not self._meta.filtering[field_name] in (ALL, ALL_WITH_RELATIONS):
            # Must be an explicit whitelist.
            if not filter_type in self._meta.filtering[field_name]:
                raise InvalidFilterError("'%s' is not an allowed filter on the '%s' field." % (filter_type, field_name))

        if self.fields[field_name].attribute is None:
            raise InvalidFilterError("The '%s' field has no 'attribute' for searching with." % field_name)

        if len(filter_bits) == 0:
            # Only a field provided, match with provided filter type
            return [self.fields[field_name].attribute] + [filter_type]
        elif len(filter_bits) == 1 and filter_bits[0] in self.get_query_terms(field_name):
            # Match with valid filter type (i.e. contains, startswith, Etc.)
            return [self.fields[field_name].attribute] + filter_bits
        else:
            # Check to see if it's a relational lookup and if that's allowed.
            if not getattr(self.fields[field_name], 'is_related', False):
                raise InvalidFilterError("The '%s' field does not support relations." % field_name)

            if not self._meta.filtering[field_name] == ALL_WITH_RELATIONS:
                raise InvalidFilterError("Lookups are not allowed more than one level deep on the '%s' field." % field_name)

            # Recursively descend through the remaining lookups in the filter,
            # if any. We should ensure that all along the way, we're allowed
            # to filter on that field by the related resource.
            related_resource = self.fields[field_name].get_related_resource(None)
            next_field_name = filter_bits[0]
            next_filter_bits = filter_bits[1:]
            next_filter_type = related_resource.resolve_filter_type(next_field_name, next_filter_bits, filter_type)

            return [self.fields[field_name].attribute] + related_resource.check_filtering(next_field_name,
                                                                                          next_filter_type,
                                                                                          next_filter_bits)

    def get_query_terms(self, field_name):
        """ Helper to determine supported filter operations for a field """
        if field_name not in self.fields:
            raise InvalidFilterError("The '%s' field is not a valid field" % field_name)

        try:
            django_field_name = self.fields[field_name].attribute
            django_field = self._meta.object_class._meta.get_field(django_field_name)
            if hasattr(django_field, 'field'):
                django_field = django_field.field  # related field
        except FieldDoesNotExist:
            raise InvalidFilterError("The '%s' field is not a valid field name" % field_name)

        return django_field.get_lookups().keys()

    def resolve_filter_type(self, field_name, filter_bits, default_filter_type=None):
        """ Helper to derive filter type from next segment in filter bits """

        if not filter_bits:
            # No filter type to resolve, use default
            return default_filter_type
        elif filter_bits[-1] not in self.get_query_terms(field_name):
            # Not valid, maybe related field, use default
            return default_filter_type
        else:
            # A valid filter type
            return filter_bits[-1]

    def filter_value_to_python(self, value, field_name, filters, filter_expr,
            filter_type):
        """
        Turn the string ``value`` into a python object.
        """
        try:
            if value in ['true', 'True', True]:
                value = True
            elif value in ['false', 'False', False]:
                value = False
            elif value in ('nil', 'none', 'None', None):
                value = None

            # Split on ',' if not empty string and either an in or range filter.
            if filter_type in ('in', 'range') and len(value):
                if hasattr(filters, 'getlist'):
                    value = []

                    for part in filters.getlist(filter_expr):
                        value.extend(part.split(','))
                else:
                    value = value.split(',')
            return value
        except Exception as e:
            try:
                logger = logging.getLogger("tastypie.resources.filter_value_to_python")
                logger.error("filter_value_to_python - value-%s  filters-%s filter_expr-%s"%(value, filters, filter_expr))
            except:
                pass
            raise e


    def build_filters(self, filters=None, bundle=None):
        """
        Given a dictionary of filters, create the necessary ORM-level filters.

        Keys should be resource fields, **NOT** model fields.

        Valid values are either a list of Django filter types (i.e.
        ``['startswith', 'exact', 'lte']``), the ``ALL`` constant or the
        ``ALL_WITH_RELATIONS`` constant.
        """
        # At the declarative level:
        #     filtering = {
        #         'resource_field_name': ['exact', 'startswith', 'endswith', 'contains'],
        #         'resource_field_name_2': ['exact', 'gt', 'gte', 'lt', 'lte', 'range'],
        #         'resource_field_name_3': ALL,
        #         'resource_field_name_4': ALL_WITH_RELATIONS,
        #         ...
        #     }
        # Accepts the filters as a dict. None by default, meaning no filters.
        if filters is None:
            filters = {}
        qs_filters = {}

        # if getattr(self._meta, 'queryset', None) is not None:
        #     # Get the possible query terms from the current QuerySet.
        #     query_terms = self._meta.queryset.query.query_terms
        # else:
        #     query_terms = QUERY_TERMS

        for filter_expr, value in list(filters.items()):
            filter_bits = filter_expr.split(LOOKUP_SEP)
            field_name = filter_bits.pop(0)

            if field_name not in self.fields:
                # It's not a field we know about. Move along citizen.
                continue

            filter_type = self.resolve_filter_type(field_name, filter_bits, 'exact')
            lookup_bits = self.check_filtering(field_name, filter_type, filter_bits)
            value = self.filter_value_to_python(value, field_name, filters, filter_expr, filter_type)
            qs_filter = LOOKUP_SEP.join(lookup_bits)
            qs_filters[qs_filter] = value

        return dict_strip_unicode_keys(qs_filters)

    def apply_sorting(self, obj_list, options=None):
        """
        Given a dictionary of options, apply some ORM-level sorting to the
        provided ``QuerySet``.

        Looks for the ``order_by`` key and handles either ascending (just the
        field name) or descending (the field name with a ``-`` in front).

        The field name should be the resource field, **NOT** model field.
        """
        if options is None:
            options = {}

        parameter_name = 'order_by'

        if not 'order_by' in options:
            if not 'sort_by' in options:
                # Nothing to alter the order. Return what we've got.
                return obj_list
            else:
                warnings.warn("'sort_by' is a deprecated parameter. Please use 'order_by' instead.")
                parameter_name = 'sort_by'

        order_by_args = []

        if hasattr(options, 'getlist'):
            order_bits = options.getlist(parameter_name)
        else:
            order_bits = options.get(parameter_name)

            if not isinstance(order_bits, (list, tuple)):
                order_bits = [order_bits]

        for order_by in order_bits:
            order_by_bits = order_by.split(LOOKUP_SEP)

            field_name = order_by_bits[0]
            order = ''

            if order_by_bits[0].startswith('-'):
                field_name = order_by_bits[0][1:]
                order = '-'

            if not field_name in self.fields:
                # It's not a field we know about. Move along citizen.
                raise InvalidSortError("No matching '%s' field for ordering on." % field_name)

            if not field_name in self._meta.ordering:
                raise InvalidSortError("The '%s' field does not allow ordering." % field_name)

            if self.fields[field_name].attribute is None:
                raise InvalidSortError("The '%s' field has no 'attribute' for ordering with." % field_name)

            order_by_args.append("%s%s" % (order, LOOKUP_SEP.join([self.fields[field_name].attribute] + order_by_bits[1:])))

        return obj_list.order_by(*order_by_args)

    def build_exclude(self,request,filters):
        exclude_filters = {}
        notequal = '__ne'
        for field, val in list(filters.items()):
            if field.endswith(notequal):
                exclude_filters[field[:-len(notequal)]]=val
                filters.pop(field)
        return exclude_filters

    def apply_filters(self, request, applicable_filters,exclude_filters):
        """
        An ORM-specific implementation of ``apply_filters``.

        The default simply applies the ``applicable_filters`` as ``**kwargs``,
        but should make it possible to do more advanced things.
        """
        return self.get_object_list(request).filter(**applicable_filters).exclude(
            **exclude_filters)

    def get_query_optimizer_params(self, bundle, for_list=False): #passing request to maintain consistency with get_object_list
        prefetch_related_set = set([])
        select_related_set = set([])
        use_in = ['all', 'list' if for_list else 'detail']

        def field_attr_to_related_attr_converter(attr):
            curr = ''
            for fragment in attr.split('__'):
                if curr:
                    curr = curr + "__" + fragment
                else:
                    curr = fragment
                yield curr


        for field_name, field_object in list(self.fields.items()):
            # If it's not for use in this mode, skip
            field_use_in = getattr(field_object, 'use_in', 'all')
            if callable(field_use_in):
                if not field_use_in(bundle, for_list):
                    continue
            else:
                if field_use_in not in use_in:
                    continue

            if field_object.instance_name in self._meta.prefetch_related + self._meta.select_related:
                if field_object.instance_name in self._meta.prefetch_related:
                    for attr in field_attr_to_related_attr_converter(field_object.attribute):
                        prefetch_related_set.add(attr)
                else:
                    for attr in field_attr_to_related_attr_converter(field_object.attribute):
                        select_related_set.add(attr)

                if getattr(field_object, 'is_related', False) and getattr(field_object,
                                                                          'full', False):
                    sub_resource_obj = field_object.get_related_resource(None, None)
                    sr_prefetch_related_set, sr_select_related_set = sub_resource_obj.get_query_optimizer_params(bundle, for_list=for_list)
                    sr_prefetch_related_set = ['%s__%s' %(field_object.attribute,prefetch) for prefetch in sr_prefetch_related_set]
                    sr_select_related_set = ['%s__%s' %(field_object.attribute,select_related) for select_related in sr_select_related_set]
                    prefetch_related_set.update(sr_prefetch_related_set)
                    prefetch_related_set.update(sr_select_related_set)


        return prefetch_related_set, select_related_set

    def optimize_query(self, qs, bundle, for_list=False):
        prefetch_related_set, select_related_set = self.get_query_optimizer_params(bundle, for_list=for_list)
        if len(prefetch_related_set) > 0:
            qs = qs.prefetch_related(*prefetch_related_set)
        if len(select_related_set) > 0:
            qs = qs.select_related(*select_related_set)
        return qs

    def get_object_list(self, request):
        """
        An ORM-specific implementation of ``get_object_list``.

        Returns a queryset that may have been limited by other overrides.
        """
        return self._meta.queryset._clone()

    def obj_get_list(self, bundle, **kwargs):
        """
        A ORM-specific implementation of ``obj_get_list``.

        Takes an optional ``request`` object, whose ``GET`` dictionary can be
        used to narrow the query.
        """

        filters = {}
        if hasattr(bundle.request, 'GET'):
            # Grab a mutable copy.
            filters = bundle.request.GET.copy()

        # Update with the provided kwargs.
        filters.update(kwargs)
        exclude_filters = self.build_exclude(bundle.request,filters)
        applicable_filters = self.build_filters(filters=filters,bundle=bundle)
        try:
            objects = self.apply_filters(bundle.request, applicable_filters, exclude_filters)
            objects = self.optimize_query(objects, bundle, for_list=True)
            return self.is_authorized("read_list", objects, bundle)
        except ValueError:
            raise BadRequest("Invalid resource lookup data provided (mismatched type).")

    def obj_get(self, bundle, **kwargs):
        """
        A ORM-specific implementation of ``obj_get``.

        Takes optional ``kwargs``, which are used to narrow the query to find
        the instance.
        """
        optimize_query = kwargs.pop('_optimize_query',False)
        try:
            if kwargs.get("pk") and not kwargs.get("pk").isdigit():
                raise ImmediateResponse(response=self.error_response(bundle.request, {"error_message":"Invalid 'id' given!"}))
            object_list = self.get_object_list(bundle.request).filter(**kwargs)
            if optimize_query:
                object_list = self.optimize_query(object_list, bundle)
            stringified_kwargs = u", ".join([u"%s=%s" % (k, v) for k, v in list(kwargs.items())])

            if len(object_list) <= 0:
                raise self._meta.object_class.DoesNotExist("Couldn't find an instance of '%s' which matched '%s'." % (self._meta.object_class.__name__, stringified_kwargs))
            elif len(object_list) > 1:
                raise MultipleObjectsReturned("More than '%s' matched '%s'." % (self._meta.object_class.__name__, stringified_kwargs))

            bundle.obj = object_list[0]
            self.is_authorized("read_detail", object_list, bundle)
            return bundle.obj
        except ValueError:
            raise NotFound("Invalid resource lookup data provided (mismatched type).")

    def obj_create(self, bundle, **kwargs):
        """
        A ORM-specific implementation of ``obj_create``.
        """
        bundle.obj = self._meta.object_class()

        for key, value in list(kwargs.items()):
            setattr(bundle.obj, key, value)


        self.is_authorized("create_detail", self.get_object_list(bundle.request), bundle)
        bundle = self.preprocess('create_detail', bundle)
        self.validate_to_one_subresource(bundle)

        bundle = self.full_hydrate(bundle)
        bundle = self.save(bundle)
        self.fire_event('detail_created', args=(self.get_object_list(bundle.request), bundle))
        return bundle

    def lookup_kwargs_with_identifiers(self, bundle, kwargs):
        """
        Kwargs here represent uri identifiers Ex: /repos/<user_id>/<repo_name>/
        We need to turn those identifiers into Python objects for generating
        lookup parameters that can find them in the DB
        """
        lookup_kwargs = {}
        bundle.obj = self.get_object_list(bundle.request).model()
        # Override data values, we rely on uri identifiers
        bundle.data.update(kwargs)
        # We're going to manually hydrate, as opposed to calling
        # ``full_hydrate``, to ensure we don't try to flesh out related
        # resources & keep things speedy.
        bundle = self.hydrate(bundle)

        for identifier in kwargs:
            if identifier == self._meta.detail_uri_name:
                lookup_kwargs[identifier] = kwargs[identifier]
                continue

            if identifier not in self.fields: continue
            field_object = self.fields[identifier]

            # Skip readonly or related fields.
            if field_object.readonly is True or getattr(field_object, 'is_related', False):
                continue

            # Check for an optional method to do further hydration.
            method = getattr(self, "hydrate_%s" % identifier, None)

            if method:
                bundle = method(bundle)

            if field_object.attribute:
                value = field_object.hydrate(bundle)

            lookup_kwargs[field_object.attribute] = value

        return lookup_kwargs

    def obj_update(self,bundle,skip_errors=False,**kwargs):
        """
        A ORM-specific implementation of ``obj_update``.
        """
        if not bundle.obj or not self.get_bundle_detail_data(bundle):
            try:
                lookup_kwargs = self.lookup_kwargs_with_identifiers(bundle, kwargs)
            except:
                # if there is trouble hydrating the data, fall back to just
                # using kwargs by itself (usually it only contains a "pk" key
                # and this will work fine.
                lookup_kwargs = kwargs

            try:
                bundle.obj = self.obj_get(bundle=bundle, _optimize_query=True, **lookup_kwargs)
            except ObjectDoesNotExist:
                raise NotFound("A model instance matching the provided arguments could not be found.")
        bundle = self.preprocess('update_detail', bundle)
        bundle = self.full_hydrate(bundle)
        self.authorized_update_detail(self.get_object_list(bundle.request), bundle)
        bundle = self.save(bundle, skip_errors=skip_errors)
        self.fire_event('detail_updated', args=(self.get_object_list(bundle.request), bundle))
        return bundle

    def obj_delete_list(self, bundle, **kwargs):
        """
        A ORM-specific implementation of ``obj_delete_list``.
        """
        objects_to_delete = self.obj_get_list(bundle=bundle, **kwargs)
        deletable_objects = self.authorized_delete_list(objects_to_delete, bundle)
        bundle = self.preprocess('delete_list', bundle)

        if hasattr(deletable_objects, 'delete'):
            # It's likely a ``QuerySet``. Call ``.delete()`` for efficiency.
            deletable_objects.delete()
        else:
            for authed_obj in deletable_objects:
                authed_obj.delete()
        self.fire_event('list_deleted', args=(deletable_objects, bundle))

    def obj_delete_list_for_update(self, bundle, **kwargs):
        """
        A ORM-specific implementation of ``obj_delete_list_for_update``.
        """
        objects_to_delete = self.obj_get_list(bundle=bundle, **kwargs)

        deletable_objects = self.is_authorized("update_list", objects_to_delete, bundle)
        bundle = self.preprocess('update_list', bundle)
        if hasattr(deletable_objects, 'delete'):
            # It's likely a ``QuerySet``. Call ``.delete()`` for efficiency.
            deletable_objects.delete()
        else:
            for authed_obj in deletable_objects:
                authed_obj.delete()

    def obj_delete(self, bundle, **kwargs):
        """
        A ORM-specific implementation of ``obj_delete``.

        Takes optional ``kwargs``, which are used to narrow the query to find
        the instance.
        """
        if not hasattr(bundle.obj, 'delete'):
            try:
                bundle.obj = self.obj_get(bundle=bundle, **kwargs)
            except ObjectDoesNotExist:
                raise NotFound("A model instance matching the provided arguments could not be found.")

        self.authorized_delete_detail(self.get_object_list(bundle.request), bundle)
        bundle = self.preprocess('delete_detail', bundle)
        self.fire_event('pre_detail_deleted', args=(self.get_object_list(bundle.request), bundle))
        bundle.obj.delete()
        self.fire_event('detail_deleted', args=(self.get_object_list(bundle.request), bundle))

    @commit_on_success()
    def patch_list(self, request, **kwargs):
        """
        An ORM-specific implementation of ``patch_list``.

        Necessary because PATCH should be atomic (all-success or all-fail)
        and the only way to do this neatly is at the database level.
        """
        return super(BaseModelResource, self).patch_list(request, **kwargs)

    def rollback(self, bundles):
        """
        A ORM-specific implementation of ``rollback``.

        Given the list of bundles, delete all models pertaining to those
        bundles.
        """
        for bundle in bundles:
            if bundle.obj and self.get_bundle_detail_data(bundle):
                bundle.obj.delete()

    def create_identifier(self, obj):
        if IS_DJANGO_1_4:
            return u"%s.%s.%s" % (obj._meta.app_label, obj._meta.module_name, obj.pk)
        else:
            return u"%s.%s.%s" % (
                obj._meta.app_label, obj._meta.object_name.lower(), obj.pk
            )

    def trigger_field_changes(self, bundle):
        '''
        Triggers change events on fields that are listening
        '''
        for field_name, field_object in list(self.fields.items()):
            if field_object.readonly:
                continue

            if field_name in bundle.original_data and \
                    bundle.data[field_name] != bundle.original_data[field_name] and field_object.change_handler:
                field_object.change_handler(bundle, bundle.data[field_name],
                                            bundle.original_data[field_name])

    def save_obj(self, bundle):
        # Save FKs just in case.
        self.save_related(bundle)
        # Save the main object.
        bundle.obj.save()
        # Now pick up the M2M bits.
        # RK: M2M hydrate already done in hydrate.
        self.save_m2m(bundle)
        return bundle

    def save(self, bundle, skip_errors=False):
        self.is_valid(bundle)

        if bundle.errors and not skip_errors:
            raise ImmediateResponse(response=self.error_response(bundle.request, bundle.errors))

        # Check if they're authorized.
        if bundle.obj.pk:
            self.authorized_update_detail(self.get_object_list(bundle.request), bundle)
            obj_update = True
        else:
            self.is_authorized("create_detail", self.get_object_list(bundle.request), bundle)
            obj_update = False

        bundle = self.save_obj(bundle)
        bundle.objects_saved.add(self.create_identifier(bundle.obj))


        if obj_update and hasattr(bundle, 'original_data'):
            self.trigger_field_changes(bundle)
        return bundle

    def save_related(self, bundle):
        """
        Handles the saving of related non-M2M data.

        Calling assigning ``child.parent = parent`` & then calling
        ``Child.save`` isn't good enough to make sure the ``parent``
        is saved.

        To get around this, we go through all our related fields &
        call ``save`` on them if they have related, non-M2M data.
        M2M data is handled by the ``ModelResource.save_m2m`` method.
        """
        for field_name, field_object in list(self.fields.items()):
            if not getattr(field_object, 'is_related', False):
                continue

            if getattr(field_object, 'is_m2m', False):
                continue

            if field_object.readonly:
                continue

            if not field_object.attribute:
                continue

            if field_object.readonly:
                continue
            if field_object.blank and field_name not in bundle.data:
                continue

            field_object.save(bundle)
            '''
            # Get the object.
            try:
                related_obj = getattr(bundle.obj, field_object.attribute)
            except ObjectDoesNotExist:
                related_obj = bundle.related_objects_to_save.get(field_object.attribute, None)

            # Because sometimes it's ``None`` & that's OK.
            if related_obj:
                if field_object.related_name:
                    if not self.get_bundle_detail_data(bundle):
                        bundle.obj.save()

                    setattr(related_obj, field_object.related_name, bundle.obj)

                related_resource = field_object.get_related_resource(related_obj)

                # Before we build the bundle & try saving it, let's make sure we
                # haven't already saved it.
                obj_id = self.create_identifier(related_obj)

                if obj_id in bundle.objects_saved:
                    # It's already been saved. We're done here.
                    continue

                if bundle.data.get(field_name) and hasattr(bundle.data[field_name], 'keys'):
                    # Only build & save if there's data, not just a URI.
                    related_bundle = related_resource.build_bundle(
                        obj=related_obj,
                        data=bundle.data.get(field_name),
                        request=bundle.request,
                        objects_saved=bundle.objects_saved
                    )
                    related_resource.save(related_bundle)

                setattr(bundle.obj, field_object.attribute, related_obj)
            '''

    def save_m2m(self, bundle):
        """
        Handles the saving of related M2M data.

        Due to the way Django works, the M2M data must be handled after the
        main instance, which is why this isn't a part of the main ``save`` bits.

        Currently slightly inefficient in that it will clear out the whole
        relation and recreate the related data as needed.
        """
        for field_name, field_object in list(self.fields.items()):
            if not getattr(field_object, 'is_m2m', False):
                continue

            if not field_object.attribute:
                continue

            if field_object.readonly:
                continue

            #no saving on edit for subresources
            if isinstance(field_object, fields.BaseSubResourceField) and\
                    bundle.obj.id:
                continue

            field_object.save(bundle)

            '''
            # Get the manager.
            related_mngr = None

            if isinstance(field_object.attribute, six.string_types):
                related_mngr = getattr(bundle.obj, field_object.attribute)
            elif callable(field_object.attribute):
                related_mngr = field_object.attribute(bundle)

            if not related_mngr:
                continue

            if hasattr(related_mngr, 'clear'):
                # FIXME: Dupe the original bundle, copy in the new object &
                #        check the perms on that (using the related resource)?

                # Clear it out, just to be safe.
                related_mngr.clear()

            related_objs = []

            for related_bundle in bundle.data[field_name]:
                related_resource = field_object.get_related_resource(bundle.obj)

                # Before we build the bundle & try saving it, let's make sure we
                # haven't already saved it.
                obj_id = self.create_identifier(related_bundle.obj)

                if obj_id in bundle.objects_saved:
                    # It's already been saved. We're done here.
                    continue

                # Only build & save if there's data, not just a URI.
                updated_related_bundle = related_resource.build_bundle(
                    obj=related_bundle.obj,
                    data=related_bundle.data,
                    request=bundle.request,
                    objects_saved=bundle.objects_saved
                )

                #Only save related models if they're newly added.
                if updated_related_bundle.obj._state.adding:
                    related_resource.save(updated_related_bundle)
                related_objs.append(updated_related_bundle.obj)

            related_mngr.add(*related_objs)
            '''

    def detail_uri_kwargs(self, bundle_or_obj):
        """
        Given a ``Bundle`` or an object (typically a ``Model`` instance),
        it returns the extra kwargs needed to generate a detail URI.

        By default, it uses the model's ``pk`` in order to create the URI.
        """
        kwargs = {}

        if isinstance(bundle_or_obj, Bundle):
            kwargs[self._meta.detail_uri_name] = getattr(bundle_or_obj.obj, self._meta.detail_uri_name)
        else:
            kwargs[self._meta.detail_uri_name] = getattr(bundle_or_obj, self._meta.detail_uri_name)

        return kwargs


class ModelResource(six.with_metaclass(ModelDeclarativeMetaclass, BaseModelResource)):
    pass


class NamespacedModelResource(ModelResource):
    """
    A ModelResource subclass that respects Django namespaces.
    """
    def _build_reverse_url(self, name, args=None, kwargs=None):
        namespaced = "%s:%s" % (self._meta.urlconf_namespace, name)
        return reverse(namespaced, args=args, kwargs=kwargs)


# Based off of ``piston.utils.coerce_put_post``. Similarly BSD-licensed.
# And no, the irony is not lost on me.
def convert_post_to_VERB(request, verb):
    """
    Force Django to process the VERB.
    """
    if request.method == verb:
        if hasattr(request, '_post'):
            del(request._post)
            del(request._files)

        try:
            request.method = "POST"
            request._load_post_and_files()
            request.method = verb
        except AttributeError:
            request.META['REQUEST_METHOD'] = 'POST'
            request._load_post_and_files()
            request.META['REQUEST_METHOD'] = verb
        setattr(request, verb, request.POST)

    return request


def convert_post_to_put(request):
    return convert_post_to_VERB(request, verb='PUT')


def convert_post_to_patch(request):
    return convert_post_to_VERB(request, verb='PATCH')


##
#Base Resource for mongo-db
##


class Document(dict):
    # dictionary-like object for mongodb documents.
    __getattr__ = dict.get

class MongoDBResource(Resource):
    """
    Base Resource for mongodb.
    NOTE: alter it f using obj_create and
    """

    class Meta(object):
        pass

    def get_collection(self):
        """
        Encapsulates collection name.
        """

        try:
            return self._meta.db[self._meta.collection]
        except AttributeError:
            raise ImproperlyConfigured("Define a collection in your resource.")

    def get_object_list(self, bundle=None, request=None, **kwargs):
        """
        Maps mongodb documents to Document class.
        """
        raise NotImplementedError("Dude write the function in each resource!")

    def obj_get_list(self,bundle, **kwargs):
        """
        Maps mongodb documents to Document class.
        """
        self.is_authenticated(bundle.request)
        filters = {}

        if hasattr(bundle.request, 'GET'):
            filters = dict(iter(bundle.request.GET.copy().items()))
        # Update with the provided kwargs.
        if "format" in filters:
            del filters['format']
        return self.is_authorized("read_list", self.get_object_list(bundle=bundle,filters=filters,**kwargs), bundle)

    def obj_get(self,bundle=None, request=None, **kwargs):
        """
        Returns mongodb document from provided id.
        """
        self.is_authenticated(bundle.request)
        obj = Document(self.get_collection().find_one({
            "_id": ObjectId(kwargs.get("pk"))
        }))
        self.is_authorized("read_detail", obj, bundle)
        return obj

    def obj_create(self, bundle, **kwargs):
        """
        Creates mongodb document from POST data.
        """

        self.is_authorized("create_detail", self.get_object_list(request=bundle.request), bundle)
        self.get_collection().insert(bundle.data)
        return bundle

    def obj_update(self, bundle, request=None, **kwargs):
        """
        Updates mongodb document.
        """
        self.is_authorized("update_detail",self.get_object_list(request=bundle.request), bundle)
        self.get_collection().update({
            "_id": ObjectId(kwargs.get("pk"))
        }, {
            "$set": bundle.data
        })
        return bundle

    def obj_delete(self, request=None, **kwargs):
        """
        Removes single document from collection
        """
        self.is_authorized("delete_detail",self.get_object_list(request=bundle.request), bundle)
        self.get_collection().remove({ "_id": ObjectId(kwargs.get("pk")) })

    def obj_delete_list(self, request=None, **kwargs):
        """
        Removes all documents from collection
        """
        self.is_authorized("delete_detail",self.get_object_list(request=bundle.request), bundle)
        self.get_collection().remove()

    def get_resource_uri(self, bundle=None, **kwargs):
        """
        Returns resource URI for bundle or object.
        """
        api_name = self.resource_uri_kwargs()['api_name']

        if bundle==None:
            return reverse("api_dispatch_list", kwargs={"resource_name": self._meta.resource_name, "api_name":api_name})

        if isinstance(bundle, Bundle):
            pk = bundle.obj._id
        else:
            pk = bundle._id

        return reverse("api_dispatch_detail", kwargs={"resource_name": self._meta.resource_name,"pk": pk , "api_name":api_name })
