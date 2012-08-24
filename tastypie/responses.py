from tastypie import http
from django.http import HttpResponse
from tastypie.utils import get_current_func_name, get_request_class
from django.utils.cache import patch_cache_control

class ResponseHandler(object):

    def _handle_500(self, request, e):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request, e)

    def get_application_error_class(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)

    def get_response_notfound_class(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)
        

    def return_response_type(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)

    def handle_cache_control(self, request, response):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request, response)

        
    def return_bad_request(self, request, *args, **kwargs):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)

        
    def return_not_implemented(self, request, *args, **kwargs):
        method = getattr(self, 'return_not_implemented_%s' % get_request_class(request))
        return method(request, *args, **kwargs)

    def return_no_content(self, request, *args, **kwargs):
        method = getattr(self, 'return_no_content_%s' % get_request_class(request))
        return method(request, *args, **kwargs)
            
    def create_response(self, request, content, content_type=None, **response_kwargs):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request, content, content_type, **response_kwargs)


    def get_application_error_class_wsgirequest(self, request):
        return http.HttpApplicationError

    def get_response_notfound_class_wsgirequest(self, request):
        return http.HttpResponseNotFound

    def handle_cache_control_wsgirequest(self, request, response):    
        if request.is_ajax() and not response.has_header("Cache-Control"):
            # IE excessively caches XMLHttpRequests, so we're disabling
            # the browser cache here.
            # See http://www.enhanceie.com/ie/bugs.asp for details.
            patch_cache_control(response, no_cache=True)            

    def return_response_type_wsgirequest(self, request):
        return HttpResponse

    def create_response_wsgirequest(self, request, content, content_type=None, **response_kwargs):
        return HttpResponse(content=content, content_type=content_type,**response_kwargs)

