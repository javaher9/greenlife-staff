from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from django.utils.deprecation import MiddlewareMixin


class CustomerCsrfMiddleware(MiddlewareMixin):
    """Use Django's normal origin, referer and token checks with the member app's hosts."""

    def __init__(self, get_response):
        super().__init__(get_response)
        self.customer_policy = CsrfViewMiddleware(get_response)
        self.review_origins = {f"https://{host}" for host in settings.ME_REVIEW_HOSTS}
        self.customer_policy.allowed_origins_exact.update(self.review_origins)
        self.customer_policy.csrf_trusted_origins_hosts.extend(settings.ME_REVIEW_HOSTS)

    def process_view(self, request, callback, callback_args, callback_kwargs):
        if settings.LAN_MODE or not request.path_info.startswith("/customer/"):
            return None
        # A public TLS proxy can deliver the final hop to Django over HTTP.
        # Select the customer policy by the browser's exact HTTPS origin on that hop.
        if request.is_secure() or request.META.get("HTTP_ORIGIN") in self.review_origins:
            return self.customer_policy.process_view(request, callback, callback_args, callback_kwargs)
        return None
