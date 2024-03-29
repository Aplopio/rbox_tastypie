from __future__ import unicode_literals
from tastypie.bundle import Bundle
from tastypie.resources import ModelResource
from tastypie.exceptions import NotFound
from django.urls import resolve, Resolver404, get_script_prefix


class GenericResource(ModelResource):
    """
    Provides a stand-in resource for GFK relations.
    """
    def __init__(self, resources, *args, **kwargs):
        self.resource_mapping = dict((r._meta.resource_name, r) for r in resources)
        return super(GenericResource, self).__init__(*args, **kwargs)


    def build_bundle(self, obj=None, data=None, request=None, objects_saved=None):
        if obj is None:
            if data is None or 'resource_uri' not in data:
                raise NotFound("The data provided is not sufficient to resolve a generic resource")
            else:
                uri = data['resource_uri']
                chomped_uri = self.get_chomped_uri(uri)
            try:
                view, args, kwargs = resolve(chomped_uri)
                resource_name = kwargs['resource_name']
                resource_class = self.resource_mapping[resource_name]
            except (Resolver404, KeyError):
                raise NotFound("The URL provided '%s' was not a link to a valid resource." % uri)
            
            resource = resource_class(api_name=self._meta.api_name)
            return resource.build_bundle(obj, data, request, objects_saved)
        return super(GenericResource, self).build_bundle(obj, data, request, objects_saved)

    def get_chomped_uri(self, uri):
        prefix = get_script_prefix()
        chomped_uri = uri

        if prefix and chomped_uri.startswith(prefix):
            chomped_uri = chomped_uri[len(prefix)-1:]

        return chomped_uri



    def get_via_uri(self, uri, request=None):
        """
        This pulls apart the salient bits of the URI and populates the
        resource via a ``obj_get``.

        Optionally accepts a ``request``.

        If you need custom behavior based on other portions of the URI,
        simply override this method.
        """
        chomped_uri = self.get_chomped_uri(uri)
        try:
            view, args, kwargs = resolve(chomped_uri)
            resource_name = kwargs['resource_name']
            resource_class = self.resource_mapping[resource_name]
        except (Resolver404, KeyError):
            raise NotFound("The URL provided '%s' was not a link to a valid resource." % uri)

        parent_resource = resource_class(api_name=self._meta.api_name)
        kwargs = parent_resource.remove_api_resource_names(kwargs)
        #bundle = Bundle(request=request) #Not sure why we are instantiating directly. Changing it to build_bundle
        bundle = parent_resource.build_bundle(request=request)
        return parent_resource.obj_get(bundle, **kwargs)
