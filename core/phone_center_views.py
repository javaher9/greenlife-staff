from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_safe

from .follow_up_views import can_access_management_follow_ups, management_follow_up_agenda


PHONE_ASSISTANTS = (
    {
        'id': 'yasaman',
        'name': 'یاسمن',
        'role': 'تماس اول و مشاوره',
        'greeting': 'سلام، من یاسمن، کارشناس ارشد گرین‌لایف هستم. برای مشاوره یا پیگیری تماس گرفتید؟',
    },
    {
        'id': 'camellia',
        'name': 'کاملیا',
        'role': 'پیگیری درخواست و هماهنگی نوبت',
        'greeting': 'سلام، من کاملیا، کارشناس ارشد گرین‌لایف هستم. برای هماهنگی مشاوره در خدمتم.',
    },
    {
        'id': 'rose',
        'name': 'رز',
        'role': 'هپی‌کال و پیگیری پس از مراجعه',
        'greeting': 'سلام، من رز، کارشناس ارشد گرین‌لایف هستم. بفرمایید چطور می‌تونم راهنمایی‌تان کنم؟',
    },
)


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
    return render(request, 'core/phone_center.html', {
        'phone_assistants': PHONE_ASSISTANTS,
        'phone_follow_ups': (
            reverse('phone_center_follow_ups') if can_access_management_follow_ups(request.user) else ''
        ),
    })


@login_required
@never_cache
def phone_center_follow_ups(request):
    if not can_access_phone_center(request.user):
        raise PermissionDenied
    return management_follow_up_agenda(request)
