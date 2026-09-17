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

        # Let finance managers correct a mistyped amount on the original
        # transaction while keeping an immutable old/new audit trail.
        from .finance_amount_correction import install_finance_amount_correction
        install_finance_amount_correction()

        # Keep the call-center staff cartable available as a small left-side
        # dock with operator-selected frequent contacts. This extends only the
        # existing call-center response injection and does not touch manager UI.
        from .call_center_dock import install_call_center_dock
        install_call_center_dock()

        # Improve low-contrast performance-card captions without changing the
        # dashboard flow; wide screens place the explanation beside the value.
        from .call_center_performance_readability import install_call_center_performance_readability
        install_call_center_performance_readability()

        # Recolor only neutral-black inherited buttons on the staff dashboard;
        # semantic green/purple/blue controls keep their existing brand colors.
        from .call_center_button_palette import install_call_center_button_palette
        install_call_center_button_palette()

        # Reserve extra horizontal space for the longer call-status action so
        # labels such as «تماس انجام شد» / «تماس گرفته شد» never get clipped.
        from .call_center_action_layout import install_call_center_action_layout
        install_call_center_action_layout()
