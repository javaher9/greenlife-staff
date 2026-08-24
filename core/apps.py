from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field='django.db.models.BigAutoField'
    name='core'

    def ready(self):
        # Register account-integrity hooks after Django has loaded the app.
        from . import signals  # noqa: F401
