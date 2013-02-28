__author__ = 'Daniel Lindsley, Cody Soyland, Matt Croydon, Josh Bohde & Issac Kelly'

'''
__version__ = (0, 9, 12, 'alpha')
from django.core.handlers.wsgi import WSGIRequest
from response_dispatcher import HttpResponseDispatcher
from response_router import ResponseRouter
response_router_obj = ResponseRouter()
response_router_obj[WSGIRequest] = HttpResponseDispatcher()
'''
__version__ = (0, 9, 13, 'beta')
