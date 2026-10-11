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
from .bulk_sms_dispatch import (
    prepare_campaign, approve_campaign, change_campaign, suppress_number,
)
from .models import BulkSmsCampaign, BulkSmsRecipient, BulkSmsOptOut
from django.db.models import Count, Q



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
        'bulk_recent_campaigns':BulkSmsCampaign.objects.filter(created_by=request.user).order_by('-id')[:12],
        'bulk_optout_count':BulkSmsOptOut.objects.count(),
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
        result=audience_preview(keys, combine=payload.get('combine','any'), date_filter=payload.get('date_filter'))
    except (UnicodeDecodeError,json.JSONDecodeError,AttributeError,TypeError,ValueError) as exc:
        return JsonResponse({'ok':False,'error':str(exc)[:180]},status=400)
    return JsonResponse({'ok':True,**result})


@login_required
@require_POST
@never_cache
def bulk_sms_campaign_api(request):
    """Prepare, explicitly approve, pause, resume, cancel and suppress via REST."""
    if not _may_manage_bulk_sms(request.user):
        raise PermissionDenied('ارسال انبوه فقط برای مدیریت ارشد است.')
    try:
        payload=json.loads(request.body)
        if not isinstance(payload,dict):
            raise ValueError('درخواست معتبر نیست.')
        action=payload.get('action')
        if action=='prepare':
            result=prepare_campaign(
                user=request.user,keys=payload.get('segments'),
                combine=payload.get('combine','any'),
                date_filter=payload.get('date_filter'),
                body=payload.get('body'),
            )
            return JsonResponse({'ok':True,**result})
        if action=='approve':
            item=approve_campaign(
                campaign_id=int(payload['campaign_id']),user=request.user,
                count=payload.get('count'),
                attested=payload.get('consent_attested') is True,
                typed=payload.get('typed'),
            )
            return JsonResponse({'ok':True,'id':item.pk,'status':item.status,
                'message':'کمپین با تأیید شما به صف ارسال افزوده شد.'})
        if action in ('pause','resume','cancel'):
            item=change_campaign(
                campaign_id=int(payload['campaign_id']),
                user=request.user,action=action,
            )
            return JsonResponse({'ok':True,'id':item.pk,'status':item.status})
        if action=='optout':
            item=suppress_number(payload.get('number'),source='executive')
            return JsonResponse({'ok':True,'number_masked':str(item)})
        raise ValueError('دستور نامعتبر است.')
    except (ValueError,TypeError,KeyError,AttributeError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        return JsonResponse({'ok':False,'error':str(exc)[:180]},status=400)


@login_required
@require_GET
@never_cache
def bulk_sms_campaigns_status_api(request):
    if not _may_manage_bulk_sms(request.user):
        raise PermissionDenied('مشاهده کمپین‌های گروهی مجاز نیست.')
    campaigns=(BulkSmsCampaign.objects.filter(created_by=request.user)
        .annotate(
            pending=Count('recipients',filter=Q(recipients__status='pending')),
            sending=Count('recipients',filter=Q(recipients__status='sending')),
            accepted=Count('recipients',filter=Q(recipients__status='accepted')),
            failed=Count('recipients',filter=Q(recipients__status='failed')),
            skipped=Count('recipients',filter=Q(recipients__status='skipped')),
        ).order_by('-pk')[:15])
    return JsonResponse({'ok':True,'campaigns':[
        {
            'id':item.pk,'status':item.status,'total':item.recipient_count,
            'pending':item.pending,'sending':item.sending,
            'accepted':item.accepted,'failed':item.failed,'skipped':item.skipped,
            'created_at':item.created_at.isoformat(),
        } for item in campaigns
    ]})
