from __future__ import print_function
from __future__ import unicode_literals
from django.core.management.base import BaseCommand
from tastypie.compat import get_user_model, get_username_field
from tastypie.models import ApiKey


class Command(BaseCommand):
    help = "Goes through all users and adds API keys for any that don't have one."

    def handle(self, *args, **options):
        """Goes through all users and adds API keys for any that don't have one."""
        self.verbosity = int(options.get('verbosity', 1))
        User = get_user_model()
        username_field = get_username_field()

        for user in User.objects.all().iterator():
            username = getattr(user, username_field)

            try:
                api_key = ApiKey.objects.get(user=user)

                if not api_key.key:
                    # Autogenerate the key.
                    api_key.save()

                    if self.verbosity >= 1:
                        print(u"Generated a new key for '%s'" % username)
            except ApiKey.DoesNotExist:
                api_key = ApiKey.objects.create(user=user)

                if self.verbosity >= 1:
                    print(u"Created a new key for '%s'" % username)
