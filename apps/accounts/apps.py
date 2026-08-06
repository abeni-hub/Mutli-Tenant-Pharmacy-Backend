from django.apps import AppConfig
from django.db.models.signals import post_migrate


class AccountsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.accounts"

    def ready(self) -> None:
        from django.conf import settings

        if settings.configured:
            from django.core.management import call_command

            def seed_demo_users(sender, **kwargs):
                call_command("seed_demo_users", verbosity=0)

            post_migrate.connect(seed_demo_users, sender=self)
