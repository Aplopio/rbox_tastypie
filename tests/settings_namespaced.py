from __future__ import absolute_import
from .settings import *
INSTALLED_APPS.append('basic')
INSTALLED_APPS.append('namespaced')

ROOT_URLCONF = 'namespaced.api.urls'
