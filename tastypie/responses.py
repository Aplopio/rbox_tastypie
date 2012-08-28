from tastypie import http
from django.http import HttpResponse
from tastypie.utils import get_current_func_name, get_request_class
from django.utils.cache import patch_cache_control


class ResponseHandler(object):

    def get_application_error_class(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)

    def get_response_notfound_class(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)
        

    def get_default_response_class(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)

    def get_created_response_class(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)

    def get_no_content_response(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)

    def get_method_notallowed_response(self, request, content):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request, content)
            
    def get_unauthorized_response_class(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)

    def get_accepted_response_class(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)        

    def get_not_found_response(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)

    def get_multiple_choices_response(self, request, content):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request, content)


    def handle_cache_control(self, request, response):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request, response)

        
    def get_bad_request_response(self, request, content):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request, content)

    def get_too_many_request_response(self, request):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request)

    def get_created_response(self, request, location):
        method = getattr(self, '%s_%s' % (get_current_func_name(), get_request_class(request)))
        return method(request, location)
        
    def get_not_implemented_response(self, request, *args, **kwargs):
        method = getattr(self, 'return_not_implemented_%s' % get_request_class(request))
        return method(request, *args, **kwargs)

    def get_unauthorized_request_response(self, request):
        method = getattr(self, 'return_not_implemented_%s' % get_request_class(request))
        return method(request)

        

    def get_unauthorized_request_response_wsgirequest(self, request):
        return http.HttpUnauthorized()        

            
    def get_application_error_class_wsgirequest(self, request):
        return http.HttpApplicationError

    def get_response_notfound_class_wsgirequest(self, request):
        return http.HttpResponseNotFound

    def get_unauthorized_response_class_wsgirequest(self, request):
        return http.HttpUnauthorized

    def handle_cache_control_wsgirequest(self, request, response):    
        if request.is_ajax() and not response.has_header("Cache-Control"):
            # IE excessively caches XMLHttpRequests, so we're disabling
            # the browser cache here.
            # See http://www.enhanceie.com/ie/bugs.asp for details.
            patch_cache_control(response, no_cache=True)

        return response

    def get_default_response_class_wsgirequest(self, request):
        return HttpResponse

    def create_response_wsgirequest(self, request, content, response_class=HttpResponse, content_type=None, **response_kwargs):
        return response_class(content=content, content_type=content_type,**response_kwargs)

    def get_created_response_class_wsgirequest(self, request):
        return http.HttpCreated

    def get_no_content_response_wsgirequest(self, request):
        return http.HttpNoContent()

    def get_not_found_response_wsgirequest(self, request):
        return http.HttpNotFound()

    def get_multiple_choices_response_wsgirequest(self, request, content):
        return http.HttpMultipleChoices(content)

    def get_accepted_response_class_wsgirequest(self, request):
        return http.HttpAccepted

    def get_bad_request_response_wsgirequest(self, request, content):
        return http.HttpBadRequest(content=content)

    def get_method_notallowed_response_wsgirequest(self, request, content):
        return http.HttpMethodNotAllowed(content)

    def get_too_many_request_response_wsgirequest(self, request):
        return http.HttpTooManyRequests()

    def get_created_response_wsgirequest(self, request, location):
        return http.HttpCreated(location=location)

    def get_not_implemented_response_wsgirequest(self, request):
        return http.HttpNotImplemented()
        