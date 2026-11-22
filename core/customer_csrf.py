from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware


class CustomerCsrfMiddleware(CsrfViewMiddleware):
    """Use Django's normal origin, referer and token checks with the member app's hosts."""

    def __init__(self, get_response):
        super().__init__(get_response)
        self.customer_policy = CsrfViewMiddleware(get_response)
        self.customer_policy.allowed_origins_exact.update(
            f"https://{host}" for host in settings.ME_REVIEW_HOSTS
        )
        self.customer_policy.csrf_trusted_origins_hosts.extend(settings.ME_REVIEW_HOSTS)

    def process_view(self, request, callback, callback_args, callback_kwargs):
        if request.is_secure() and request.path_info.startswith("/customer/"):
            return self.customer_policy.process_view(request, callback, callback_args, callback_kwargs)
        return super().process_view(request, callback, callback_args, callback_kwargs)
