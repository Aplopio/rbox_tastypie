from __future__ import unicode_literals
from functools import partial
from tastypie import fields
from tastypie.resources import Resource
from tastypie.exceptions import ApiFieldError
from django.db import models
from django.core.exceptions import ObjectDoesNotExist
from .resources import GenericResource
from tastypie.exceptions import ApiFieldError, NotFound, HydrationError

class GenericForeignKeyField(fields.ToOneField):
    """
    Provides access to GenericForeignKey objects from the django content_types
    framework.
    """

    def __init__(self, to, attribute, **kwargs):
        if not isinstance(to, dict):
            raise ValueError('to field must be a dictionary in GenericForeignKeyField')

        if len(to) <= 0:
            raise ValueError('to field must have some values')

        for k, v in list(to.items()):
            if not issubclass(k, models.Model) or not issubclass(v, Resource):
                raise ValueError('to field must map django models to tastypie resources')

        super(GenericForeignKeyField, self).__init__(to, attribute, **kwargs)


    def resource_from_data(self, fk_resource, data, request=None, related_obj=None, related_name=None):
        if 'resource_uri' not in data:
            raise ApiFieldError("Related data provided for %s does not have resource_uri field" %self.instance_name)
        return self.resource_from_uri(fk_resource, data['resource_uri'], request, related_obj, related_name)

    def resource_from_pk(self, fk_resource, value, **kwargs):
        fk_resource = self.get_related_resource(value)
        if isinstance(related_resource, GenericResource):
            raise ApiFieldError("Related object %s does is not of the right type" %value)
        return super(GenericForeignKeyField, self).resource_from_pk(fk_resource, value, **kwargs)


    def get_related_resource(self, related_instance):
        #self._to_class = self.to.get(type(related_instance), None)
        to_class = self.to.get(type(related_instance),None)
        if to_class:
            related_resource = to_class()
            if related_resource._meta.api_name is None:
                if self._resource and not self._resource._meta.api_name is None:
                    related_resource._meta.api_name = self._resource._meta.api_name
            # Try to be efficient about DB queries.
            related_resource.instance = related_instance
            return related_resource
        else:
            return super(GenericForeignKeyField, self).get_related_resource(related_instance)

        #if self._to_class is None:
        #    raise TypeError('no resource for model %s' % type(related_instance))


    @property
    def to_class(self):
        if self._to_class and not issubclass(GenericResource, self._to_class):
            #this case should never happen. self._to_class should always be none
            return self._to_class

        return partial(GenericResource, resources=list(self.to.values()))

    def resource_from_uri(self, fk_resource, uri, request=None, related_obj=None, related_name=None):
        try:
            obj = fk_resource.get_via_uri(uri, request=request)
            fk_resource = self.get_related_resource(obj)
            return super(GenericForeignKeyField, self).resource_from_uri(fk_resource, uri, request, related_obj, related_name)
        except ObjectDoesNotExist:
            raise ApiFieldError("Could not find the provided object via resource URI '%s'." % uri)

    def build_related_resource(self, *args, **kwargs):
        self._to_class = None
        return super(GenericForeignKeyField, self).build_related_resource(*args, **kwargs)
