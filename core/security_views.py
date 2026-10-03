from urllib.parse import urlsplit

from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import reverse
from django.views.csrf import csrf_failure as django_csrf_failure


def csrf_failure(request, reason=''):
    """Recover safely from stale/mismatched CSRF tokens without disabling CSRF.

    Authenticated staff can hit this after a deploy or long-lived tablet tab.
    Redirect only to a same-host GET destination so Django can issue a fresh
    token on the next render. All unsafe requests still require a valid token.
    """
    if getattr(request, 'user', None) and request.user.is_authenticated:
        target = request.META.get('HTTP_REFERER') or request.path or reverse('dashboard')
        try:
            parsed = urlsplit(target)
            if parsed.netloc and parsed.netloc != request.get_host():
                target = request.path or reverse('dashboard')
        except Exception:
            target = request.path or reverse('dashboard')

        # Avoid a redirect loop back into a failed POST endpoint with queryless
        # browser resubmission semantics; redirect itself is always a GET.
        messages.warning(
            request,
            'امنیت صفحه تازه‌سازی شد. لطفاً همان اقدام را یک‌بار دیگر انجام دهید.',
        )
        response = HttpResponseRedirect(target)
        response['Cache-Control'] = 'no-store'
        return response

    return django_csrf_failure(request, reason=reason)
