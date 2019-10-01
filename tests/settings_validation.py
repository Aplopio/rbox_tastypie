from __future__ import absolute_import
from .settings import *
INSTALLED_APPS.append('basic')
INSTALLED_APPS.append('validation')

ROOT_URLCONF = 'validation.api.urls'
