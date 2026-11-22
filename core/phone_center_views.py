from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe


def can_access_phone_center(user):
    if not getattr(user, 'is_authenticated', False) or not user.is_active:
        return False
    if user.is_superuser or user.username.lower() in settings.EXECUTIVE_USERNAMES:
        return True
    profile = getattr(user, 'profile', None)
    return bool(profile and profile.is_active and profile.role in ('admin', 'internal_manager'))


@login_required
@require_safe
@never_cache
def phone_center(request):
    if not can_access_phone_center(request.user):
        raise PermissionDenied
    return render(request, 'core/phone_center.html')
