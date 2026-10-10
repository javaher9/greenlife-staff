"""Executive-only mass SMS audience discovery and safe REST preview.

Sending is deliberately not enabled here until opt-out, consent, queue,
campaign idempotency, and per-day throttling are enforced.
"""
import json

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST

from .bulk_sms_audiences import audience_preview, catalog


def _may_manage_bulk_sms(user):
    if not user.is_authenticated or not user.is_active:
        return False
    if user.is_superuser:
        return True
    profile=getattr(user,'profile',None)
    if profile and profile.is_active and profile.role=='admin':
        return True
    return (user.username or '').lower() in settings.EXECUTIVE_USERNAMES


@login_required
@require_GET
@never_cache
def bulk_sms_groups(request):
    if not _may_manage_bulk_sms(request.user):
        raise PermissionDenied('دسترسی به گروه‌های پیامک فقط برای مدیریت است.')
    groups={}
    for segment in catalog():
        groups.setdefault(segment['group'],[]).append(segment)
    response=render(request,'core/bulk_sms_groups.html',{
        'segment_groups':groups,
        'total_segment_types':sum(map(len,groups.values())),
    })
    response['Cache-Control']='no-store, private'
    return response


@login_required
@require_POST
@never_cache
def bulk_sms_preview_api(request):
    if not _may_manage_bulk_sms(request.user):
        raise PermissionDenied('دسترسی به پیش‌نمایش پیامک فقط برای مدیریت است.')
    try:
        payload=json.loads(request.body)
        keys=payload.get('segments')
        result=audience_preview(keys)
    except (UnicodeDecodeError,json.JSONDecodeError,AttributeError,TypeError,ValueError) as exc:
        return JsonResponse({'ok':False,'error':str(exc)[:180]},status=400)
    return JsonResponse({'ok':True,**result})
