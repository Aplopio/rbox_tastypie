from __future__ import unicode_literals
from __future__ import absolute_import


__author__ = 'Daniel Lindsley & the Tastypie core team'
__version__ = (0, 19, 0, 'dev')

from django.core.handlers.wsgi import WSGIRequest
from .response_dispatcher import HttpResponseDispatcher
from .response_router import ResponseRouter
response_router_obj = ResponseRouter()
response_router_obj[WSGIRequest] = HttpResponseDispatcher()

