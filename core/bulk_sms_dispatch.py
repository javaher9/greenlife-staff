"""Explicitly approved mass-SMS campaigns, suppression and bounded worker dispatch.

A campaign is never sent by a GET, a preview, or even a draft creation.
Only the executive's separate approval moves frozen recipients into the
existing production SMS worker. Failed/ambiguous requests are never auto-retried.
"""
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from .bulk_sms_audiences import _iran_number, audience_preview
from .models import (
    ApiServerSettings, BulkSmsCampaign, BulkSmsRecipient, BulkSmsOptOut,
)

MAX_CAMPAIGN_RECIPIENTS=2500
MAX_DAILY_ATTEMPTS=400
MAX_WORKER_BATCH=12
COOLDOWN_DAYS=7
DRAFT_LIFETIME_MINUTES=45


def _gateway_active():
    config=ApiServerSettings.load()
    return bool(config.is_enabled and config.is_configured)


def _assert_gateway():
    if not _gateway_active():
        raise ValueError('درگاه REST API پیامک فعال یا پیکربندی نشده است.')


def prepare_campaign(*, user, keys, combine, date_filter, body):
    """Freeze valid numbers once; no provider call and no send side effect."""
    _assert_gateway()
    if not isinstance(body,str) or not 3 <= len(body.strip()) <= 560:
        raise ValueError('متن پیامک باید بین ۳ تا ۵۶۰ نویسه باشد.')
    body=body.strip()
    if not ('لغو 11' in body or 'لغو۱۱' in body or 'لغو: 11' in body):
        body+='\nلغو 11'
    if len(body)>600:
        raise ValueError('طول پیامک از حد مجاز بیشتر است.')
    preview=audience_preview(
        keys,combine=combine,date_filter=date_filter,
        include_numbers=True,max_contacts=20000,
    )
    if preview['truncated']:
        raise ValueError('گروه بسیار بزرگ است؛ ابتدا با فیلترهای زمان یا ترکیب محدودتر کنید.')
    numbers=preview.pop('_numbers')
    if not numbers:
        raise ValueError('هیچ مخاطب معتبری برای ارسال پیدا نشد.')
    if len(numbers)>MAX_CAMPAIGN_RECIPIENTS:
        raise ValueError('حداکثر ۲۵۰۰ مخاطب در یک کمپین مجاز است؛ مخاطبان را محدودتر انتخاب کنید.')
    blocklist=set(BulkSmsOptOut.objects.filter(number__in=numbers).values_list('number',flat=True))
    cooldown=set(BulkSmsRecipient.objects.filter(
        number__in=numbers,status='accepted',
        attempted_at__gte=timezone.now()-timedelta(days=COOLDOWN_DAYS),
    ).values_list('number',flat=True))
    excluded=blocklist|cooldown
    eligible=[n for n in numbers if n not in excluded]
    if not eligible:
        raise ValueError('همه مخاطبان در فهرست عدم ارسال یا فاصله حفاظتی هستند.')
    with transaction.atomic():
        campaign=BulkSmsCampaign.objects.create(
            created_by=user,body=body,segments=keys,combine=combine,
            date_filter=date_filter if isinstance(date_filter,dict) else {},
            recipient_count=len(eligible),excluded_count=len(excluded),
        )
        BulkSmsRecipient.objects.bulk_create([
            BulkSmsRecipient(campaign=campaign,number=n) for n in eligible
        ],batch_size=400)
    return {
        'id':campaign.pk,'count':len(eligible),'excluded':len(excluded),
        'body':campaign.body,'status':'draft',
        'sample_masked':[n[:4]+'***'+n[-4:] for n in eligible[:5]],
    }


def approve_campaign(*, campaign_id, user, count, attested, typed):
    """Separate user confirmation, lock against duplicate approvals."""
    if attested is not True or typed != 'تایید':
        raise ValueError('تأیید رضایت گیرندگان و عبارت «تایید» ضروری است.')
    _assert_gateway()
    with transaction.atomic():
        item=BulkSmsCampaign.objects.select_for_update().filter(
            pk=campaign_id,created_by=user,
        ).first()
        if item is None or item.status!='draft':
            raise ValueError('این پیش‌نویس برای تأیید در دسترس نیست.')
        if item.created_at<timezone.now()-timedelta(minutes=DRAFT_LIFETIME_MINUTES):
            raise ValueError('پیش‌نویس منقضی شده است؛ مخاطبان را دوباره انتخاب کنید.')
        if not isinstance(count,int) or count!=item.recipient_count:
            raise ValueError('تعداد گیرندگان با پیش‌نمایش نهایی برابر نیست.')
        if not item.recipient_count or BulkSmsRecipient.objects.filter(
            campaign=item,
        ).count()!=item.recipient_count:
            raise ValueError('فهرست گیرندگان ناقص است.')
        item.consent_attested=True
        item.status='queued'
        item.approved_at=timezone.now()
        item.save(update_fields=['consent_attested','status','approved_at','updated_at'])
    return item


def change_campaign(*, campaign_id, user, action):
    """Pause queued sends or permanently cancel outstanding rows."""
    if action not in ('pause','resume','cancel'):
        raise ValueError('دستور نامعتبر است.')
    with transaction.atomic():
        item=BulkSmsCampaign.objects.select_for_update().filter(
            pk=campaign_id,created_by=user,
        ).first()
        if not item or item.status not in ('queued','paused'):
            raise ValueError('کمپین در وضعیت قابل تغییر نیست.')
        if action=='pause' and item.status!='queued':
            raise ValueError('کمپین قبلاً متوقف شده است.')
        if action=='resume' and item.status!='paused':
            raise ValueError('کمپین متوقف نیست.')
        item.status={'pause':'paused','resume':'queued','cancel':'cancelled'}[action]
        item.save(update_fields=['status','updated_at'])
        if action=='cancel':
            BulkSmsRecipient.objects.filter(campaign=item,status='pending').update(
                status='skipped',reason='لغو توسط مدیریت',
            )
    return item


def suppress_number(number, *, source='manual'):
    """Idempotent opt-out, including automatic reply 11."""
    clean=_iran_number(number)
    if not clean:
        raise ValueError('شماره موبایل ایرانی معتبر نیست.')
    item,_=BulkSmsOptOut.objects.get_or_create(
        number=clean,defaults={'source':source[:32]},
    )
    BulkSmsRecipient.objects.filter(number=clean,status='pending').update(
        status='skipped',reason='درخواست عدم دریافت پیامک',
    )
    return item


def _finalize_finished_campaign(campaign_id):
    if not BulkSmsRecipient.objects.filter(
        campaign_id=campaign_id,status__in=('pending','sending'),
    ).exists():
        BulkSmsCampaign.objects.filter(pk=campaign_id,status='queued').update(status='completed')


def process_bulk_sms(batch_size=MAX_WORKER_BATCH):
    """Executed by existing SMS worker, never within a web request.

    Uses an exclusive lock on the singleton API settings row to serialize
    global send quotas among concurrent workers. Claims are durable before
    gateway calls; unknown outcomes must not be retried automatically.
    """
    from .sms import send_sms
    if not _gateway_active():
        return 0
    now=timezone.now()
    # Do not retry a message if the process died after contacting the gateway.
    BulkSmsRecipient.objects.filter(
        status='sending',updated_at__lt=now-timedelta(minutes=6),
    ).update(status='failed',reason='نتیجه درگاه نامشخص؛ ارسال دوباره خودکار ممنوع')
    attempts=0
    for _ in range(max(1,min(batch_size,MAX_WORKER_BATCH))):
        with transaction.atomic():
            ApiServerSettings.objects.select_for_update().get(pk=1)
            recent=BulkSmsRecipient.objects.filter(
                attempted_at__gte=timezone.now()-timedelta(hours=24),
            ).count()
            if recent>=MAX_DAILY_ATTEMPTS:
                break
            entry=(BulkSmsRecipient.objects.select_for_update(skip_locked=True)
                   .filter(status='pending',campaign__status='queued',campaign__consent_attested=True)
                   .order_by('campaign__approved_at','pk').first())
            if not entry:
                break
            opted_out=BulkSmsOptOut.objects.filter(number=entry.number).exists()
            too_recent=BulkSmsRecipient.objects.filter(
                number=entry.number,status='accepted',
                attempted_at__gte=timezone.now()-timedelta(days=COOLDOWN_DAYS),
            ).exclude(pk=entry.pk).exists()
            if opted_out or too_recent:
                entry.status='skipped'
                entry.reason='عدم ارسال یا پیامک گروهی در ۷ روز اخیر'
                entry.save(update_fields=['status','reason','updated_at'])
                _finalize_finished_campaign(entry.campaign_id)
                continue
            entry.status='sending'
            entry.attempted_at=timezone.now()
            entry.save(update_fields=['status','attempted_at','updated_at'])
            campaign_id=entry.campaign_id
            campaign_body=entry.campaign.body
            recipient_id=entry.pk
            recipient_number=entry.number
            owner=entry.campaign.created_by
        try:
            send_sms(recipient_number,campaign_body,purpose='bulk',created_by=owner)
        except Exception:
            # The gateway may have accepted a timed-out request. Never retry.
            new_status='failed'
            reason='خطای درگاه یا نتیجه نامشخص؛ بدون ارسال مجدد خودکار'
        else:
            new_status='accepted'
            reason=''
        BulkSmsRecipient.objects.filter(pk=recipient_id,status='sending').update(
            status=new_status,reason=reason,
        )
        _finalize_finished_campaign(campaign_id)
        attempts+=1
    return attempts
