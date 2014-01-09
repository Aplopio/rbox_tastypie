from __future__ import unicode_literals


__author__ = 'Daniel Lindsley & the Tastypie core team'
__version__ = (0, 11, 1, 'dev')

from django.core.handlers.wsgi import WSGIRequest
from response_dispatcher import HttpResponseDispatcher
from response_router import ResponseRouter
response_router_obj = ResponseRouter()
response_router_obj[WSGIRequest] = HttpResponseDispatcher()

