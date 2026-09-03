from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field='django.db.models.BigAutoField'
    name='core'

    def ready(self):
        # Register account-integrity hooks after Django has loaded the app.
        from . import signals  # noqa: F401
        # Digital referral models live in their own module to keep the public
        # acquisition network isolated from the staff referral network.
        from . import digital_referral_models  # noqa: F401
