from __future__ import unicode_literals
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
import django

__all__ = ['AUTH_USER_MODEL', 'get_username_field', 'get_user_model']

AUTH_USER_MODEL = getattr(settings, 'AUTH_USER_MODEL', 'auth.User')


def get_username_field():
    # Django 1.5+ compatibility
    if django.VERSION >= (1, 5):
        try:
            from django.contrib.auth import get_user_model as get_user
            User = get_user()
            return User.USERNAME_FIELD
        except ImproperlyConfigured:
            # The the users model might not be read yet.
            # This can happen is when setting up the create_api_key signal, in your
            # custom user module.
            return None
    else:
        return 'username'


def get_user_model():
    if django.VERSION >= (1, 5):
        try:
            from django.contrib.auth import get_user_model as get_user
            User = get_user()
            return User
        except ImproperlyConfigured:
            # The the users model might not be read yet.
            # This can happen is when setting up the create_api_key signal, in your
            # custom user module.
            return None
    else:
        from django.contrib.auth.models import User
        return User
