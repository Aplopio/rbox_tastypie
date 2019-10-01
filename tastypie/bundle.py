from __future__ import unicode_literals
from builtins import object
from django.http import HttpRequest


# In a separate file to avoid circular imports...
class Bundle(object):
    """
    A small container for instances and converted data for the
    ``dehydrate/hydrate`` cycle.

    Necessary because the ``dehydrate/hydrate`` cycle needs to access data at
    different points.
    """
    def __init__(self,
                 obj=None,
                 data=None,
                 request=None,
                 related_obj=None,
                 related_name=None,
                 objects_saved=None,
                 related_objects_to_save=None,
                 parent_obj=None,
                 parent_resource=None,
                 resource=None):
        self.obj = obj
        self.data = data or {}
        self.request = request or HttpRequest()
        self.related_obj = related_obj
        self.related_name = related_name
        self.errors = {}
        self.objects_saved = objects_saved or set()
        self.parent_obj = parent_obj
        self.parent_resource = parent_resource
        self.resource = resource
        self.related_objects_to_save = related_objects_to_save or {}

    def __repr__(self):
        return "<Bundle for obj: '%s' and with data: '%s'>" % (self.obj, self.data)
