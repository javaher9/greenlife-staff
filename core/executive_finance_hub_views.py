"""Read-only executive finance navigation hub.

The hub intentionally displays no calculated financial totals until a reviewed
aggregation API is wired in. It never modifies financial records.
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.cache import never_cache


@never_cache
@login_required
def executive_finance_hub(request):
    allowed = (request.user.username or "").lower() in settings.EXECUTIVE_USERNAMES
    if not allowed:
        raise PermissionDenied("Executive finance access denied.")
    return render(request, "core/executive_finance_hub.html")
