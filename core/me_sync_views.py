"""Same-origin proxy API. Django CSRF + existing verified phone session required."""
import json
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from django.db import transaction
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods
from .customer_portal_views import _member
from .me_sync_models import MeAccountState, MeDailyAward, MeSyncAudit

KEYS = {'greenlife-interactive-preview-v1', 'greenlife-heart-v1', 'greenlife-me-member-v1',
        'greenlife-day-v1', 'greenlife-me-experience-v1', 'greenlife-me-diet-preview-v1'}
HEART = 'greenlife-heart-v1'


def reply(value, status=200):
    response = JsonResponse(value, status=status)
    response['Cache-Control'] = 'private, no-store, max-age=0'
    return response


@never_cache
def connect(request):
    if _member(request):
        return redirect('https://greenlife-me-preview.vercel.app/my/')
    return redirect('/customer/login/?next=/customer/me/connect/')


def clean_values(values):
    if not isinstance(values, dict) or set(values) - KEYS:
        raise ValueError('invalid_keys')
    if len(json.dumps(values, ensure_ascii=False)) > 150000:
        raise ValueError('too_large')
    for value in values.values():
        if not isinstance(value, dict):
            raise ValueError('invalid_value')
    member = values.get('greenlife-me-member-v1')
    if member:
        # Device-local activity history is never uploaded retroactively.
        member['events'] = []
    return values


def reconcile_heart(member, values, previous):
    heart = values.get(HEART)
    if heart is None:
        return
    today = timezone.now().astimezone(ZoneInfo('Asia/Tehran')).date()
    now = timezone.now().isoformat()
    old = previous.get(HEART, {})
    days = dict(old.get('days', {}))
    incoming = heart.get('days', {})
    if not isinstance(incoming, dict):
        raise ValueError('invalid_days')
    for key, report in incoming.items():
        try:
            day = date.fromisoformat(key)
        except (ValueError, TypeError):
            raise ValueError('invalid_day')
        if str(day) != key:
            raise ValueError('invalid_day')
        if not today - timedelta(days=6) <= day <= today:
            continue
        if not isinstance(report, dict):
            raise ValueError('invalid_report')
        food, move = report.get('food'), report.get('move')
        if type(food) is bool or type(move) is bool or food not in (None, 'skip', 0, 25, 50, 75, 100) or move not in (None, 'skip', 0, 50, 100):
            raise ValueError('invalid_report')
        days[key] = {'food': food, 'move': move, 'source': 'self_report', 'updatedAt': now}
        active = [v for v in (food, move) if v != 'skip']
        if active and all(v is not None for v in active) and sum(active) / len(active) >= 80:
            MeDailyAward.objects.get_or_create(member=member, day=day)
    # Explicit deletion is allowed only in the editable window. Award history remains.
    for key in list(days):
        if key not in incoming and str(today-timedelta(days=6)) <= key <= str(today):
            del days[key]
    days = {k: v for k, v in days.items() if k >= str(today-timedelta(days=59))}
    awards = {str(a.day): a.granted_at.isoformat() for a in MeDailyAward.objects.filter(member=member)}
    values[HEART] = {'version': 1, 'startedAt': old.get('startedAt') or (now if heart.get('startedAt') or days else None), 'days': days, 'awards': awards}


@never_cache
@require_http_methods(['GET', 'POST'])
def state(request):
    member = _member(request)
    if not member:
        return reply({'authenticated': False, 'login': '/customer/me/connect/'}, 401)
    if request.method == 'GET':
        record = MeAccountState.objects.filter(member=member).first()
        return reply({'authenticated': True, 'member': str(member.pk), 'phone': member.phone,
                      'csrf': get_token(request), 'version': record.version if record else 0,
                      'values': record.values if record else {}, 'consented': bool(record and record.consent_at)})
    if request.content_type != 'application/json' or len(request.body) > 250000:
        return reply({'error': 'invalid_request'}, 400)
    try:
        body = json.loads(request.body)
        values = clean_values(body['values'])
        if type(body.get('version')) is not int:
            raise ValueError('invalid_version')
    except (ValueError, KeyError, TypeError):
        return reply({'error': 'invalid_request'}, 400)
    with transaction.atomic():
        # Lock the stable parent row, including the first creation from two devices.
        type(member).objects.select_for_update().get(pk=member.pk)
        record, _ = MeAccountState.objects.get_or_create(member=member)
        if record.version != body['version']:
            return reply({'error': 'conflict', 'version': record.version}, 409)
        if not record.consent_at and body.get('consent') is not True:
            transaction.set_rollback(True)
            return reply({'error': 'consent_required'}, 400)
        try:
            reconcile_heart(member, values, record.values)
        except (ValueError, TypeError):
            transaction.set_rollback(True)
            return reply({'error': 'invalid_report'}, 400)
        record.values = values
        record.version += 1
        record.consent_at = record.consent_at or timezone.now()
        record.save()
        MeSyncAudit.objects.create(member=member, version=record.version, action='sync')
    return reply({'version': record.version, 'values': record.values})


@never_cache
@require_http_methods(['POST'])
def logout(request):
    for key in ('gl_customer_member_id', 'gl_customer_auth_at', 'gl_pending_phone'):
        request.session.pop(key, None)
    request.session.cycle_key()
    return reply({'ok': True})
