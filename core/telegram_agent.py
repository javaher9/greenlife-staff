import hmac
import json
import os
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .instagram_views import TELEGRAM_GROUP_NAME, _assign_instagram_lead, _telegram_source_profile
from .models import ReferralLead


DEFAULT_SERVICE_OPTIONS = (
    'لاغری',
    'مشاوره لاغری',
    'دستگاه‌های لاغری',
    'سایر',
)

_DIGIT_TRANSLATION = str.maketrans(
    '۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩',
    '01234567890123456789',
)


def _service_options():
    raw = os.getenv('TELEGRAM_SERVICE_OPTIONS', '').strip()
    if not raw:
        return list(DEFAULT_SERVICE_OPTIONS)
    values = [item.strip()[:160] for item in raw.split('|') if item.strip()]
    return values[:8] or list(DEFAULT_SERVICE_OPTIONS)


def _normalize_phone(value):
    raw = str(value or '').translate(_DIGIT_TRANSLATION).strip()
    normalized = ''.join(ch for ch in raw if ch.isdigit() or ch == '+')[:30]
    if sum(ch.isdigit() for ch in normalized) < 10:
        return ''
    return normalized


def _telegram_api(method, payload):
    token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        return {'ok': False, 'description': 'TELEGRAM_BOT_TOKEN is not configured'}

    endpoint = f"https://api.telegram.org/bot{quote(token, safe=':')}/{method}"
    body = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    request = Request(
        endpoint,
        data=body,
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urlopen(request, timeout=10) as response:
            result = json.loads(response.read().decode('utf-8') or '{}')
            return result if isinstance(result, dict) else {'ok': False}
    except (HTTPError, URLError, TimeoutError, ValueError, OSError) as exc:
        return {'ok': False, 'description': str(exc)[:300]}


def _send_message(chat_id, text, reply_markup=None):
    payload = {'chat_id': chat_id, 'text': text}
    if reply_markup:
        payload['reply_markup'] = reply_markup
    return _telegram_api('sendMessage', payload)


def _answer_callback(callback_id, text='ثبت شد'):
    return _telegram_api('answerCallbackQuery', {
        'callback_query_id': callback_id,
        'text': text,
    })


def _request_contact_keyboard():
    return {
        'keyboard': [[{
            'text': '📱 ارسال شماره موبایل',
            'request_contact': True,
        }]],
        'resize_keyboard': True,
        'one_time_keyboard': True,
        'input_field_placeholder': 'برای شروع شماره موبایل را ارسال کنید',
    }


def _service_keyboard(lead_id):
    rows = []
    for index, label in enumerate(_service_options()):
        rows.append([{
            'text': label,
            'callback_data': f'glsvc:{lead_id}:{index}',
        }])
    return {'inline_keyboard': rows}


def _telegram_identity(from_user):
    first_name = str(from_user.get('first_name') or '').strip()
    last_name = str(from_user.get('last_name') or '').strip()
    full_name = ' '.join(part for part in (first_name, last_name) if part).strip()
    return (full_name or 'مراجع تلگرام')[:140]


def _telegram_source_url(from_user, request):
    username = str(from_user.get('username') or '').strip().lstrip('@')
    if username:
        return f'https://t.me/{username}'[:500]
    return request.build_absolute_uri('/telegram/')[:500]


def _telegram_tag(user_id):
    return f'[telegram_user:{user_id}]'


def _recent_lead_for_user(user_id, *, phone='', days=1):
    queryset = ReferralLead.objects.filter(
        notes__icontains=_telegram_tag(user_id),
        created_at__gte=timezone.now() - timedelta(days=days),
    )
    if phone:
        queryset = queryset.filter(phone=phone)
    return queryset.order_by('-created_at').first()


def _active_lead_for_user(user_id):
    return (
        ReferralLead.objects
        .filter(
            notes__icontains=_telegram_tag(user_id),
            created_at__gte=timezone.now() - timedelta(days=30),
            status__in=('new', 'contacted', 'appointment'),
        )
        .order_by('-created_at')
        .first()
    )


def _append_lead_note(lead, text):
    clean = ' '.join(str(text or '').split())[:700]
    if not clean:
        return
    existing = (lead.notes or '').strip()
    lead.notes = (existing + '\n' + clean).strip()[-6000:]
    lead.save(update_fields=['notes', 'updated_at'])


def _create_or_reuse_lead(request, from_user, phone):
    user_id = from_user.get('id')
    existing = _recent_lead_for_user(user_id, phone=phone, days=1)
    if existing:
        if not existing.assigned_to_id:
            _assign_instagram_lead(
                existing,
                group_name=TELEGRAM_GROUP_NAME,
                notification_title='لید جدید تلگرام',
            )
        return existing, False

    username = str(from_user.get('username') or '').strip().lstrip('@')
    notes = [
        '[channel:telegram]',
        '[telegram_bot]',
        _telegram_tag(user_id),
    ]
    if username:
        notes.append(f'[telegram_username:{username[:80]}]')

    lead = ReferralLead.objects.create(
        referrer=_telegram_source_profile(),
        full_name=_telegram_identity(from_user),
        phone=phone,
        interested_service='',
        status='new',
        source='link',
        source_url=_telegram_source_url(from_user, request),
        notes='\n'.join(notes),
    )
    _assign_instagram_lead(
        lead,
        group_name=TELEGRAM_GROUP_NAME,
        notification_title='لید جدید تلگرام',
    )
    return lead, True


def _send_service_choice(chat_id, lead):
    _send_message(chat_id, 'شماره شما ثبت شد ✅', {'remove_keyboard': True})
    _send_message(
        chat_id,
        'برای اینکه سریع‌تر به کارشناس مناسب وصل شوید، موضوع موردنظرتان را انتخاب کنید:',
        _service_keyboard(lead.id),
    )


def _handle_callback(request, callback):
    callback_id = callback.get('id')
    from_user = callback.get('from') or {}
    user_id = from_user.get('id')
    data = str(callback.get('data') or '')
    message = callback.get('message') or {}
    chat_id = (message.get('chat') or {}).get('id')

    parts = data.split(':')
    if len(parts) != 3 or parts[0] != 'glsvc':
        if callback_id:
            _answer_callback(callback_id, 'دستور نامعتبر است')
        return

    try:
        lead_id = int(parts[1])
        option_index = int(parts[2])
        service = _service_options()[option_index]
    except (ValueError, IndexError):
        if callback_id:
            _answer_callback(callback_id, 'گزینه نامعتبر است')
        return

    lead = ReferralLead.objects.filter(
        pk=lead_id,
        notes__icontains=_telegram_tag(user_id),
    ).first()
    if not lead:
        if callback_id:
            _answer_callback(callback_id, 'این درخواست پیدا نشد')
        return

    lead.interested_service = service[:160]
    lead.save(update_fields=['interested_service', 'updated_at'])
    _append_lead_note(lead, f'[telegram_service:{service}]')

    if callback_id:
        _answer_callback(callback_id, 'ثبت شد ✅')
    if chat_id:
        _send_message(
            chat_id,
            f'موضوع «{service}» ثبت شد. یکی از کارشناسان گرین‌لایف با شما تماس می‌گیرد. 🌿',
        )


def _handle_message(request, message):
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    if not chat_id or chat.get('type') not in (None, 'private'):
        return

    from_user = message.get('from') or {}
    user_id = from_user.get('id')
    if not user_id:
        return

    text = str(message.get('text') or '').strip()
    command = text.split()[0].lower() if text.startswith('/') else ''

    if command in ('/start', '/help'):
        _send_message(
            chat_id,
            'سلام 👋\nمن دستیار تلگرام گرین‌لایف هستم. برای ثبت درخواست مشاوره، شماره موبایل خودتان را با دکمه زیر ارسال کنید. اطلاعات درمانی و تشخیص پزشکی توسط پزشک یا کارشناس انسانی بررسی می‌شود.',
            _request_contact_keyboard(),
        )
        return

    if command == '/privacy':
        _send_message(
            chat_id,
            'شماره و اطلاعاتی که اینجا می‌فرستید فقط برای ثبت درخواست و تماس کارشناسان گرین‌لایف در سیستم لید ذخیره می‌شود.',
        )
        return

    if command == '/cancel':
        _send_message(
            chat_id,
            'باشه. فرایند جدیدی ثبت نشد. هر زمان خواستید /start را بزنید.',
            {'remove_keyboard': True},
        )
        return

    contact = message.get('contact') or {}
    if contact:
        contact_user_id = contact.get('user_id')
        if contact_user_id and contact_user_id != user_id:
            _send_message(chat_id, 'لطفاً شماره متعلق به خودتان را با دکمه «ارسال شماره موبایل» بفرستید.')
            return
        phone = _normalize_phone(contact.get('phone_number'))
        if not phone:
            _send_message(chat_id, 'شماره موبایل قابل تشخیص نبود. لطفاً دوباره ارسال کنید.')
            return
        lead, _ = _create_or_reuse_lead(request, from_user, phone)
        _send_service_choice(chat_id, lead)
        return

    phone = _normalize_phone(text)
    if phone:
        lead, _ = _create_or_reuse_lead(request, from_user, phone)
        _send_service_choice(chat_id, lead)
        return

    lead = _active_lead_for_user(user_id)
    if lead:
        if text and not lead.interested_service:
            lead.interested_service = text[:160]
            lead.save(update_fields=['interested_service', 'updated_at'])
            _append_lead_note(lead, f'[telegram_service_text:{text[:160]}]')
            _send_message(chat_id, 'موضوع درخواست شما ثبت شد ✅ کارشناس گرین‌لایف بررسی می‌کند و با شما تماس می‌گیرد.')
            return
        if text:
            _append_lead_note(lead, f'[telegram_message] {text}')
            _send_message(chat_id, 'پیام شما به درخواستتان اضافه شد ✅ کارشناس گرین‌لایف آن را بررسی می‌کند.')
            return

    _send_message(
        chat_id,
        'برای شروع، لطفاً شماره موبایل خودتان را ارسال کنید تا درخواست در سیستم گرین‌لایف ثبت شود.',
        _request_contact_keyboard(),
    )


@csrf_exempt
@require_POST
def telegram_webhook(request):
    secret = os.getenv('TELEGRAM_WEBHOOK_SECRET', '').strip()
    if not secret:
        return JsonResponse({'ok': False, 'error': 'telegram_webhook_not_configured'}, status=503)

    supplied = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '').strip()
    if not supplied or not hmac.compare_digest(supplied, secret):
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    try:
        update = json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError, json.JSONDecodeError):
        return JsonResponse({'ok': False, 'error': 'invalid_json'}, status=400)
    if not isinstance(update, dict):
        return JsonResponse({'ok': False, 'error': 'invalid_update'}, status=400)

    callback = update.get('callback_query')
    if isinstance(callback, dict):
        _handle_callback(request, callback)
    else:
        message = update.get('message')
        if isinstance(message, dict):
            _handle_message(request, message)

    return JsonResponse({'ok': True})
