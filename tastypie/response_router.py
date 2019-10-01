from builtins import object
from tastypie.utils import get_request_class_name_lowered


class ResponseRouter(object):    
    def __init__(self):
        self.match = {}

    def __setitem__(self, request_class, handler):
        self.match[get_request_class_name_lowered(request_class)] = handler
        
    def __delitem__(self, request_class):
        try:
            del self._match[get_request_class_name_lowered(request_class)]
        except KeyError:
            pass

    def __getitem__(self, request_obj_or_class):
        return self.match[get_request_class_name_lowered(request_obj_or_class)]        