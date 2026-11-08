"""Public, non-persistent preview of the deployed weight intake template."""
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect, ensure_csrf_cookie
from django.views.decorators.http import require_http_methods

from .views import LIMITED_CHOICES


@never_cache
@ensure_csrf_cookie
@csrf_protect
@require_http_methods(["GET", "POST"])
def weight_preview(request):
    # No invitation, patient, SMS, or database writes belong in this preview.
    template = "intake/preview_finished.html" if request.method == "POST" else "intake/weight_form.html"
    response = render(request, template, {**LIMITED_CHOICES, "demo_mode": True})
    response["X-Robots-Tag"] = "noindex, nofollow"
    return response
