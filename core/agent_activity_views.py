from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
from hashlib import sha256

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .agent_flow import daily_flow
from .device_booking_models import BranchDeviceTypeStatus, PhysicalDevice
from .jalali import format_jalali, parse_jalali
from .channel_webhook_views import bot_connection
from .models import (
    Branch, VisitAppointment, ChannelBotSetup, ChannelMessageReceipt, InstagramIntegrationSettings, InstagramWebhookEvent,
    WhatsAppMessage, WhatsAppNumber,
)
from .views import credential_admin_required


def _objects(value):
    if isinstance(value, list):
        yield from (item for item in value if isinstance(item, dict))


def _instagram_activity(now):
    account = InstagramIntegrationSettings.objects.filter(pk=1).first()
    channel = {
        'id': 'instagram', 'name': 'اینستاگرام',
        'account': account.username if account and account.username else 'greenlifeclinics',
        'state': 'در انتظار اتصال', 'tone': 'pending',
        'metric': 'دایرکت در 250 رویداد اخیر امروز', 'count': 0,
    }
    if not account or not (account.is_enabled and account.is_connected and account.is_configured):
        return channel, []
    channel.update(state='حساب متصل', tone='connected')

    start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    recent = InstagramWebhookEvent.objects.filter(received_at__gte=start).only(
        'payload', 'received_at'
    )[:250]
    events = {}
    for event in recent:
        payload = event.payload
        if not isinstance(payload, dict) or payload.get('object') != 'instagram':
            continue
        for entry in _objects(payload.get('entry')):
            if str(entry.get('id')) != account.instagram_user_id:
                continue
            for item in _objects(entry.get('messaging')):
                message = item.get('message')
                if not isinstance(message, dict) or message.get('is_echo') or message.get('is_self'):
                    continue
                mid = message.get('mid')
                if isinstance(mid, str) and mid:
                    events.setdefault(mid, {
                        'id': 'ig-' + sha256(mid.encode()).hexdigest(), 'channel': 'instagram',
                        'name': 'اینستاگرام', 'label': 'دایرکت ورودی ثبت شد',
                        'time': event.received_at,
                    })
    channel['count'] = len(events)
    return channel, list(events.values())[:20]


def _whatsapp_activity(now):
    start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    numbers = WhatsAppNumber.objects.filter(is_active=True)
    counts = {
        row['whatsapp_number_id']: row['inbound']
        for row in WhatsAppMessage.objects.filter(
            created_at__gte=start, whatsapp_number__is_active=True, direction='inbound'
        ).values('whatsapp_number_id').annotate(inbound=Count('pk')).order_by()
    }
    channels = [{
        'id': f'wa-{number.pk}', 'name': 'واتساپ', 'account': number.label,
        'state': number.get_connection_status_display(),
        'tone': number.connection_status,
        'metric': 'پیام ورودی امروز', 'count': counts.get(number.pk, 0),
    } for number in numbers]
    if not channels:
        channels.append({
            'id': 'whatsapp', 'name': 'واتساپ', 'account': '',
            'state': 'شماره فعال تعریف نشده', 'tone': 'pending',
        })
    sent = Q(direction='outbound', status__in=('sent', 'delivered', 'read'))
    recent = WhatsAppMessage.objects.filter(
        Q(direction='inbound') | sent,
        created_at__gte=now - timedelta(days=1), whatsapp_number__is_active=True,
    ).values('id', 'whatsapp_number_id', 'whatsapp_number__label', 'direction', 'created_at')[:20]
    events = [{
        'id': f'wm-{message["id"]}', 'channel': f'wa-{message["whatsapp_number_id"]}',
        'name': 'واتساپ · ' + message['whatsapp_number__label'],
        'label': 'پیام ورودی ثبت شد' if message['direction'] == 'inbound' else 'ارسال پاسخ ثبت شد',
        'time': message['created_at'],
    } for message in recent]
    return channels, events


def _bot_activity(provider, name, now):
    account = bot_connection(provider)
    channel = {
        'id': provider, 'name': name, 'account': '', 'state': 'در انتظار تنظیم ربات', 'tone': 'pending',
    }
    if not account:
        return channel, []

    receipts = ChannelMessageReceipt.objects.filter(provider=provider, bot_id=account.bot_id)
    start = timezone.localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    recent = list(receipts.filter(received_at__gte=start).values('id', 'received_at')[:20])
    confirmed = bool(recent) or receipts.exists()
    channel.update(
        state='دریافت تأیید شده' if confirmed else 'در انتظار اولین پیام',
        tone='connected' if confirmed else 'pending',
        metric='پیام ورودی امروز', count=receipts.filter(received_at__gte=start).count(),
    )
    return channel, [{
        'id': f'{provider}-{event["id"]}', 'channel': provider, 'name': name,
        'label': 'پیام ربات دریافت شد', 'time': event['received_at'],
    } for event in recent]


def _snapshot():
    now = timezone.now()
    instagram, instagram_events = _instagram_activity(now)
    whatsapp, whatsapp_events = _whatsapp_activity(now)
    telegram, telegram_events = _bot_activity('telegram', 'تلگرام', now)
    bale, bale_events = _bot_activity('bale', 'بله', now)
    linkedin = {
        'id': 'linkedin', 'name': 'لینکدین', 'account': '',
        'state': 'در انتظار اتصال', 'tone': 'pending',
    }
    channels = [instagram, *whatsapp, telegram, bale, linkedin]
    events = sorted(
        instagram_events + whatsapp_events + telegram_events + bale_events,
        key=lambda event: event['time'], reverse=True,
    )[:20]
    for event in events:
        event['time'] = timezone.localtime(event['time']).isoformat()

    return {
        'channels': channels, 'events': events,
        'flow': daily_flow(timezone.localtime(now)),
        'updated_at': timezone.localtime(now).isoformat(),
    }


def _appointment_cards(now):
    tehran = ZoneInfo('Asia/Tehran')
    today = now.astimezone(tehran).date()
    month = format_jalali(today, persian_digits=False).rsplit('/', 1)[0]
    start = datetime.combine(parse_jalali(f'{month}/01'), time.min, tzinfo=tehran)
    names = ('نیاوران', 'پونک', 'اصفهان')
    branch_ids = {name: [] for name in names}
    for pk, label in Branch.objects.values_list('pk', 'name'):
        normalized = label.translate(str.maketrans('يك', 'یک')).replace('\u200c', '')
        for name in names:
            if name in normalized:
                branch_ids[name].append(pk)
                break
    ids_to_show = [pk for ids in branch_ids.values() for pk in ids]
    disabled_types = BranchDeviceTypeStatus.objects.filter(
        branch_id=OuterRef('branch_id'), device_type_id=OuterRef('device_type_id'), is_active=False,
    )
    devices = dict(PhysicalDevice.objects.filter(branch_id__in=ids_to_show)
        .values('branch_id').annotate(active=Count('pk', filter=(
            Q(is_active=True, device_type__is_active=True) & ~Exists(disabled_types)
        ))).order_by().values_list('branch_id', 'active'))
    rows = VisitAppointment.objects.filter(
        branch_id__in=ids_to_show,
        created_at__lte=now,
    ).values('branch_id').annotate(
        total=Count('pk'),
        done=Count('pk', filter=Q(status='completed')),
        month_total=Count('pk', filter=Q(created_at__gte=start)),
        month_done=Count('pk', filter=Q(created_at__gte=start, status='completed')),
    ).order_by()
    by_id = {row['branch_id']: row for row in rows}
    periods = []
    for prefix in ('month_', ''):
        cards = []
        for name, ids in branch_ids.items():
            total = sum(by_id.get(pk, {}).get(prefix + 'total', 0) for pk in ids)
            done = sum(by_id.get(pk, {}).get(prefix + 'done', 0) for pk in ids)
            cards.append({
                'name': name, 'available': bool(ids), 'total': total, 'done': done,
                'devices': sum(devices[pk] for pk in ids) if ids and all(pk in devices for pk in ids) else None,
                'rate': round(100 * done / total) if total else None,
            })
        maximum = max(card['total'] for card in cards)
        for card in cards:
            card['scale'] = maximum
            for metric in ('total', 'done'):
                count = card[metric]
                card[f'{metric}_level'] = 100 * count / maximum if maximum else 0
        periods.append(cards)
    return periods


@never_cache
@credential_admin_required
@require_GET
def agent_activity(request):
    saved = ChannelBotSetup.objects.in_bulk()
    bots = [{
        'id': key, 'name': name, 'setup': saved.get(key),
        'managed': any(settings.CHANNEL_BOTS[key]),
    } for key, name in ChannelMessageReceipt.PROVIDERS]
    return render(request, 'core/agent_activity.html', {'activity': _snapshot(), 'bots': bots, 'appointment_periods': _appointment_cards(timezone.now())})


@never_cache
@credential_admin_required
@require_GET
def agent_activity_snapshot(request):
    return JsonResponse(_snapshot())
