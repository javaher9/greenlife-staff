import json
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import CallCenterLeadGroup, EmployeeProfile, ReferralLead, ReferralProfile, StaffNotification


CHANNEL_LABELS = {
    'website': 'وب‌سایت',
    'instagram': 'اینستاگرام',
    'crm': 'CRM',
    'whatsapp': 'واتس‌اپ',
    'campaign': 'کمپین',
    'partner': 'همکار',
}


def _source_profile(channel):
    safe_channel = channel if channel in CHANNEL_LABELS else 'external'
    username = f'lead-source-{safe_channel}'
    user, _ = User.objects.get_or_create(
        username=username,
        defaults={
            'first_name': CHANNEL_LABELS.get(safe_channel, 'ورودی'),
            'last_name': 'Lead Hub',
            'is_active': False,
        },
    )
    if user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=['password'])
    code = f'GL{safe_channel.upper()}'[:24]
    profile, _ = ReferralProfile.objects.get_or_create(
        user=user,
        defaults={
            'referral_code': code,
            'is_active': False,
            'created_by': None,
        },
    )
    return profile


def _assign_lead(lead, channel):
    operator = (
        EmployeeProfile.objects
        .filter(role='call_center', is_active=True, user__is_active=True)
        .annotate(open_leads=Count(
            'assigned_referral_leads',
            filter=Q(assigned_referral_leads__status__in=('new', 'contacted', 'appointment')),
        ))
        .order_by('open_leads', 'id')
        .first()
    )
    if not operator:
        return None

    group_name = 'اینستاگرام جدید' if channel == 'instagram' else f'ورودی {CHANNEL_LABELS.get(channel, channel)}'
    group, _ = CallCenterLeadGroup.objects.get_or_create(
        owner=operator,
        name=group_name,
        defaults={'is_default': False},
    )
    lead.assigned_to = operator
    lead.group = group
    lead.save(update_fields=['assigned_to', 'group', 'updated_at'])
    StaffNotification.objects.create(
        user=operator.user,
        title=f'لید جدید {CHANNEL_LABELS.get(channel, channel)}',
        message=f'{lead.full_name} با شماره {lead.phone} وارد «{group_name}» شد.',
        notification_type='call_center_lead',
        related_date=timezone.localdate(),
    )
    return operator


@csrf_exempt
@require_POST
def ingest_lead(request):
    expected_token = getattr(settings, 'LEAD_INGEST_TOKEN', '')
    supplied_token = request.headers.get('X-Lead-Token', '')
    if not expected_token:
        return JsonResponse({'ok': False, 'error': 'lead_ingest_not_configured'}, status=503)
    if supplied_token != expected_token:
        return JsonResponse({'ok': False, 'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'error': 'invalid_json'}, status=400)

    full_name = str(payload.get('full_name') or payload.get('name') or '').strip()[:140]
    phone = ''.join(ch for ch in str(payload.get('phone') or payload.get('mobile') or '') if ch.isdigit() or ch == '+')[:30]
    service = str(payload.get('interested_service') or payload.get('service') or '').strip()[:160]
    channel = str(payload.get('source') or payload.get('channel') or 'crm').strip().lower()
    source_url = str(payload.get('source_url') or payload.get('url') or '').strip()[:500]
    external_id = str(payload.get('external_id') or payload.get('lead_id') or '').strip()[:120]
    campaign = str(payload.get('campaign') or payload.get('utm_campaign') or '').strip()[:120]

    if not full_name or len(phone) < 10:
        return JsonResponse({'ok': False, 'error': 'name_and_valid_phone_required'}, status=400)
    if channel not in CHANNEL_LABELS:
        channel = 'crm'

    # Idempotency: prevent the same external system from creating a rapid duplicate.
    duplicate = ReferralLead.objects.filter(
        phone=phone,
        created_at__gte=timezone.now() - timedelta(minutes=10),
        notes__icontains=f'[channel:{channel}]',
    ).order_by('-created_at').first()
    if duplicate:
        return JsonResponse({'ok': True, 'duplicate': True, 'lead_id': duplicate.id}, status=200)

    meta = [f'[channel:{channel}]']
    if external_id:
        meta.append(f'[external_id:{external_id}]')
    if campaign:
        meta.append(f'[campaign:{campaign}]')
    notes = ' '.join(meta)
    extra_notes = str(payload.get('notes') or '').strip()
    if extra_notes:
        notes = f'{notes}\n{extra_notes}'[:4000]

    lead = ReferralLead.objects.create(
        referrer=_source_profile(channel),
        full_name=full_name,
        phone=phone,
        interested_service=service,
        status='new',
        source='link',
        source_url=source_url,
        notes=notes,
    )
    operator = _assign_lead(lead, channel)

    return JsonResponse({
        'ok': True,
        'lead_id': lead.id,
        'assigned_to': operator.user.get_full_name() or operator.user.username if operator else None,
        'channel': channel,
    }, status=201)
