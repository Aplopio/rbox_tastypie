from tastypie.utils.dict import dict_strip_unicode_keys
from tastypie.utils.formatting import mk_datetime, format_datetime, format_date, format_time
from tastypie.utils.urls import trailing_slash
from tastypie.utils.validate_jsonp import is_valid_jsonp_callback_value
from tastypie.utils.timezone import now, make_aware, make_naive, aware_date, aware_datetime
import inspect

def get_current_func_name():
    """for python version greater than equal to 2.7"""
    return inspect.stack()[1][3]

def get_request_class(request):
    """Returns the class of request in lower case"""
    return request.__class__.__name__.lower()


def get_request_class_name_lowered(request_obj_or_class):
    """Returns the class of request in lower case"""
    if  isinstance(request_obj_or_class, type):
        return request_obj_or_class.__name__.lower()
    else:
        return request_obj_or_class.__class__.__name__.lower()

