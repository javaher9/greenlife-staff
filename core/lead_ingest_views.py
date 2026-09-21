import hashlib
import hmac
import json
import os
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

from django.contrib.auth.models import User
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .credential_security import decrypt_secret
from .models import Attendance, CallCenterLeadGroup, EmployeeProfile, LeaveRequest, ReferralLead, ReferralProfile, StaffNotification, WebsiteLeadIntegrationSettings


CHANNEL_LABELS = {
    'website': 'وب‌سایت',
    'instagram': 'اینستاگرام',
    'crm': 'CRM',
    'whatsapp': 'واتس‌اپ',
    'campaign': 'کمپین',
    'partner': 'همکار',
}

# Weighted call-center routing. Higher weight means a larger share of new leads.
# Current requested policy: Babayi 6, Salehi 4, regular operators 3, Abbasi 1.
OPERATOR_WEIGHT_RULES = (
    (('بابایی', 'babaei', 'babayi', 'babaee'), 6),
    (('صالحی', 'salehi'), 4),
    (('عباسی', 'abbasi'), 1),
)
DEFAULT_OPERATOR_WEIGHT = 3
FRIDAY_DUTY_MIN_WEIGHT = 8
FRIDAY_DUTY_WEIGHT_MULTIPLIER = 2
FRIDAY_DUTY_START_HOUR = 12
FRIDAY_DUTY_END_HOUR = 18

# Safe to keep in source control: this is only a SHA-256 digest of a long,
# random token. The plaintext token lives only in WordPress and can be rotated
# by setting LEAD_INGEST_TOKEN_SHA256 on the Staff server.
DEFAULT_WEBSITE_LEAD_TOKEN_SHA256 = 'fa1adf75f911f2a7cebbbaedcfbf4dffd63f639fbe4e110cba2ee9ca9baee33f'

_RESERVED_KEYS = {
    'form_id', 'form_name', 'source', 'channel', 'source_url', 'page_url', 'url',
    'external_id', 'lead_id', 'campaign', 'utm_campaign', 'utm_source',
    'utm_medium', 'utm_content', 'utm_term', 'landing_page', 'referrer',
    'referrer_url', 'page_title', 'language', 'lang', 'meta', 'metadata', 'fields',
    'cta_variant', 'cta_label', 'copy_variant',
}


def _authorized(request):
    supplied = request.headers.get('X-Lead-Token', '').strip()
    authorization = request.headers.get('Authorization', '')
    if authorization.lower().startswith('bearer '):
        supplied = authorization[7:].strip()
    if not supplied:
        supplied = request.GET.get('token', '').strip()
    if not supplied:
        return False

    # Primary source of truth: the dedicated Website Leads settings in Staff App.
    # If a DB key exists, the enable/disable switch is authoritative and legacy
    # environment variables cannot bypass it.
    config = WebsiteLeadIntegrationSettings.load()
    if config.api_key_cipher:
        if not config.is_enabled:
            return False
        expected = decrypt_secret(config.api_key_cipher)
        return bool(expected) and hmac.compare_digest(supplied, expected)

    # Backward-compatible fallback for servers that have not generated their
    # Website Leads key yet. No secret or digest is committed to source control.
    expected_plain = os.getenv('LEAD_INGEST_TOKEN', '')
    if expected_plain and hmac.compare_digest(supplied, expected_plain):
        return True

    expected_digest = os.getenv('LEAD_INGEST_TOKEN_SHA256', '').strip()
    if not expected_digest:
        return False
    supplied_digest = hashlib.sha256(supplied.encode('utf-8')).hexdigest()
    return hmac.compare_digest(supplied_digest, expected_digest)


def _merged_payload(payload):
    """Flatten common Elementor/native webhook wrappers into one dictionary."""
    merged = dict(payload)
    for key in ('fields', 'meta', 'metadata'):
        nested = payload.get(key)
        if isinstance(nested, dict):
            for nested_key, value in nested.items():
                merged.setdefault(str(nested_key), value)
    return merged


def _clean_scalar(value, limit=500):
    if isinstance(value, (list, tuple)):
        value = ', '.join(str(item) for item in value if item not in (None, ''))
    elif isinstance(value, dict):
        return ''
    return str(value or '').strip()[:limit]


def _lookup(payload, aliases=(), contains=(), limit=500):
    for alias in aliases:
        if alias in payload:
            value = _clean_scalar(payload.get(alias), limit)
            if value:
                return value
    lowered = [(str(key).lower(), key) for key in payload]
    for needle in contains:
        needle = needle.lower()
        for lowered_key, original_key in lowered:
            if needle in lowered_key:
                value = _clean_scalar(payload.get(original_key), limit)
                if value:
                    return value
    return ''


_DIGIT_TRANSLATION = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def _normalize_valid_lead_phone(raw_value):
    """Return a canonical lead phone or '' when the value is not a plausible phone.

    Iranian mobile numbers are stored in local 09xxxxxxxxx form. Non-Iranian
    numbers must be explicitly international (+countrycode...), which blocks
    random 10/11-digit bot payloads from becoming leads.
    """
    raw = _clean_scalar(raw_value, 80).translate(_DIGIT_TRANSLATION).strip()
    compact = ''.join(ch for ch in raw if ch.isdigit() or ch == '+')
    if compact.count('+') > 1 or ('+' in compact and not compact.startswith('+')):
        return ''

    digits = ''.join(ch for ch in compact if ch.isdigit())
    # Iran local mobile: 09xxxxxxxxx
    if len(digits) == 11 and digits.startswith('09'):
        return digits
    # Iran mobile without trunk prefix: 9xxxxxxxxx
    if len(digits) == 10 and digits.startswith('9') and not compact.startswith('+'):
        return '0' + digits
    # Iran country code, with or without +: 989xxxxxxxxx
    if len(digits) == 12 and digits.startswith('989'):
        return '0' + digits[2:]
    # Foreign numbers are allowed only in explicit E.164-like + format.
    if compact.startswith('+') and 10 <= len(digits) <= 15 and not digits.startswith('98'):
        return '+' + digits
    return ''


def _phone_value(payload):
    candidates = []
    exact = ('phone', 'mobile', 'tel', 'telephone', 'email')
    for key in exact:
        if key in payload:
            candidates.append(payload.get(key))
    for key, value in payload.items():
        lowered = str(key).lower()
        if any(term in lowered for term in ('phone', 'mobile', 'tel', 'موبایل', 'تلفن', 'شماره')):
            candidates.append(value)
    for value in candidates:
        phone = _normalize_valid_lead_phone(value)
        if phone:
            return phone
    return ''


def _honeypot_triggered(payload):
    """Recognize fields reserved only for invisible anti-bot inputs."""
    for key in ('honeypot', 'hp_field', 'website_hp', 'company_hp', 'botcheck'):
        if _clean_scalar(payload.get(key), 120):
            return True
    return False


def _utm_from_url(source_url):
    if not source_url:
        return {}
    try:
        query = parse_qs(urlparse(source_url).query)
    except ValueError:
        return {}
    result = {}
    for key in ('utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term'):
        values = query.get(key) or []
        if values:
            result[key] = str(values[0])[:120]
    return result


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


def _operator_identity(operator):
    user = operator.user
    identity = ' '.join(
        part for part in (user.first_name, user.last_name, user.username) if part
    ).lower()
    return identity.replace('ي', 'ی').replace('ك', 'ک')


def _operator_weight(operator):
    identity = _operator_identity(operator)
    for aliases, weight in OPERATOR_WEIGHT_RULES:
        if any(alias in identity for alias in aliases):
            return weight
    return DEFAULT_OPERATOR_WEIGHT


def _effective_operator_weight(operator, now=None):
    local_now = timezone.localtime(now or timezone.now())
    today = local_now.date()
    base = _operator_weight(operator)
    if today.weekday() != 4 or not (FRIDAY_DUTY_START_HOUR <= local_now.hour < FRIDAY_DUTY_END_HOUR):
        return base
    attendance = Attendance.objects.filter(
        user=operator.user,
        date=today,
        check_in__isnull=False,
    ).only('check_in', 'check_out').first()
    if not attendance:
        return base
    if attendance.check_out and timezone.localtime(attendance.check_out) <= local_now:
        return base
    return max(base * FRIDAY_DUTY_WEIGHT_MULTIPLIER, FRIDAY_DUTY_MIN_WEIGHT)


def _eligible_operator_user_ids(day=None):
    day = day or timezone.localdate()
    present_ids = set(
        Attendance.objects.filter(
            date=day,
            check_in__isnull=False,
            check_out__isnull=True,
            user__profile__role='call_center',
            user__profile__is_active=True,
            user__is_active=True,
        ).values_list('user_id', flat=True)
    )
    if not present_ids:
        return set()
    leave_ids = set(
        LeaveRequest.objects.filter(
            user_id__in=present_ids,
            status='approved',
            start_date__lte=day,
            end_date__gte=day,
        ).values_list('user_id', flat=True)
    )
    return present_ids - leave_ids


def _assign_lead(lead, channel):
    today = timezone.localdate()
    eligible_user_ids = _eligible_operator_user_ids(today)
    if not eligible_user_ids:
        return None
    operators = list(
        EmployeeProfile.objects
        .filter(
            role='call_center',
            is_active=True,
            user__is_active=True,
            user_id__in=eligible_user_ids,
        )
        .select_related('user')
        .annotate(
            today_leads=Count(
                'assigned_referral_leads',
                filter=Q(assigned_referral_leads__created_at__date=today),
            )
        )
    )
    if not operators:
        return None

    # Weighted fair routing. Using (today_leads + 1) / weight prevents low-weight
    # operators from winning every zero-count tie at the start of the day while
    # still guaranteeing that they receive their proportional share over time.
    operator = min(
        operators,
        key=lambda op: (
            (op.today_leads + 1) / _effective_operator_weight(op),
            -_effective_operator_weight(op),
            op.id,
        ),
    )

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
    if not _authorized(request):
        return JsonResponse({'ok': False, 'error': 'unauthorized'}, status=401)

    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        payload = request.POST.dict()
    if not isinstance(payload, dict):
        return JsonResponse({'ok': False, 'error': 'invalid_payload'}, status=400)

    data = _merged_payload(payload)
    if _honeypot_triggered(data):
        return JsonResponse({'ok': False, 'error': 'spam_rejected'}, status=400)
    phone = _phone_value(data)
    full_name = _lookup(
        data,
        aliases=('full_name', 'name'),
        contains=('full name', 'نام و نام', 'نام'),
        limit=140,
    )
    if not full_name:
        full_name = 'لید وب‌سایت'

    service = _lookup(
        data,
        aliases=('interested_service', 'service', 'interest'),
        contains=('service', 'interest', 'خدمت', 'موضوع', 'درخواست'),
        limit=160,
    )
    channel = _lookup(data, aliases=('source', 'channel'), limit=30).lower() or 'website'
    if channel not in CHANNEL_LABELS:
        channel = 'website'

    source_url = _lookup(
        data,
        aliases=('source_url', 'page_url', 'url', 'Page URL', 'page URL'),
        contains=('page url', 'page_url'),
        limit=500,
    )
    external_id = _lookup(data, aliases=('external_id', 'lead_id', 'submission_id'), limit=120)
    form_id = _lookup(data, aliases=('form_id',), contains=('form id',), limit=120)
    form_name = _lookup(data, aliases=('form_name',), contains=('form name',), limit=180)
    page_title = _lookup(data, aliases=('page_title',), contains=('page title',), limit=240)
    landing_page = _lookup(data, aliases=('landing_page',), limit=500)
    referrer_url = _lookup(data, aliases=('referrer_url', 'referrer'), limit=500)
    language = _lookup(data, aliases=('language', 'lang'), limit=20)
    cta_variant = _lookup(data, aliases=('cta_variant',), limit=80)
    cta_label = _lookup(data, aliases=('cta_label',), limit=180)
    copy_variant = _lookup(data, aliases=('copy_variant',), limit=40)

    url_utm = _utm_from_url(source_url)
    utm = {
        key: _lookup(data, aliases=(key,), limit=120) or url_utm.get(key, '')
        for key in ('utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term')
    }
    campaign = _lookup(data, aliases=('campaign', 'utm_campaign'), limit=120) or utm['utm_campaign']

    if not phone:
        return JsonResponse({'ok': False, 'error': 'valid_phone_required'}, status=400)

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
    if cta_variant:
        meta.append(f'[cta_variant:{cta_variant}]')

    website_meta = {
        'page_url': source_url,
        'page_title': page_title,
        'form_id': form_id,
        'form_name': form_name,
        'landing_page': landing_page,
        'referrer_url': referrer_url,
        'language': language,
        'cta_variant': cta_variant,
        'cta_label': cta_label,
        'copy_variant': copy_variant,
        **{key: value for key, value in utm.items() if value},
    }
    website_meta = {key: value for key, value in website_meta.items() if value}

    notes_parts = [' '.join(meta)]
    message = _lookup(data, aliases=('notes', 'message'), contains=('message', 'پیام', 'توضیح'), limit=2500)
    if message:
        notes_parts.append(message)
    if website_meta:
        notes_parts.append('[attribution]' + json.dumps(website_meta, ensure_ascii=False, separators=(',', ':')))
    notes = '\n'.join(notes_parts)[:4000]

    lead = ReferralLead.objects.create(
        referrer=_source_profile(channel),
        full_name=full_name[:140],
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
        'source_url': source_url,
        'cta_variant': cta_variant,
    }, status=201)
