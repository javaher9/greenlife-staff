from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field='django.db.models.BigAutoField'
    name='core'

    def ready(self):
        # Register account-integrity hooks after Django has loaded the app.
        from . import signals  # noqa: F401

        # Attribute approved appointment payments to the call-center owner/lead.
        from . import finance_attribution  # noqa: F401

        # Route every lead source through the same concurrency-safe,
        # weighted round-robin engine.
        from .lead_routing import install_unified_lead_routing
        install_unified_lead_routing()
