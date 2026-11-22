"""Record one trusted end-of-call event and report overall phone volumes."""
from datetime import UTC, date, datetime, time, timedelta
import json

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .phone_call_metric_models import PhoneCallMetric
from .phone_ingestion import authorized_feeder, opaque_call_id, phone_ingest_token


TOKEN_ENV = 'STAFF_PHONE_METRICS_TOKEN'
COUNTERS = {
    'count': Count('pk'),
    'inbound': Count('pk', filter=Q(direction='inbound')),
    'outbound': Count('pk', filter=Q(direction='outbound')),
    'answered': Count('pk', filter=Q(outcome='answered')),
    'unanswered': Count('pk', filter=Q(outcome='unanswered')),
}


def _event(body):
    data = json.loads(body)
    if not isinstance(data, dict) or data.keys() != {
        'call_id', 'direction', 'outcome', 'occurred_at', 'duration_seconds',
    }:
        raise ValueError
    call_id = opaque_call_id(data.pop('call_id'))
    stamp = data['occurred_at']
    if not isinstance(stamp, str) or len(stamp) > 40:
        raise ValueError
    occurred_at = parse_datetime(stamp)
    if occurred_at is None or timezone.is_naive(occurred_at):
        raise ValueError
    occurred_at = occurred_at.astimezone(UTC)
    duration = data['duration_seconds']
    if (
        data['direction'] not in ('inbound', 'outbound')
        or data['outcome'] not in ('answered', 'unanswered')
        or type(duration) is not int or not 0 <= duration < 2 ** 31
        or (data['outcome'] == 'unanswered' and duration != 0)
        or occurred_at > timezone.now() + timedelta(minutes=5)
    ):
        raise ValueError
    data['occurred_at'] = occurred_at
    return call_id, data


@csrf_exempt
@never_cache
@require_POST
def ingest_metric(request):
    token = phone_ingest_token(TOKEN_ENV)
    if not token:
        return JsonResponse({'error': 'intake_unavailable'}, status=503)
    if not authorized_feeder(request, token):
        return JsonResponse({'error': 'authorization_required'}, status=401)
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'unsupported_media_type'}, status=415)
    if len(request.body) > 1024:
        return JsonResponse({'error': 'invalid_call_event'}, status=400)
    try:
        call_id, fields = _event(request.body)
    except (ValueError, UnicodeError, OverflowError, RecursionError):
        return JsonResponse({'error': 'invalid_call_event'}, status=400)
    event, created = PhoneCallMetric.objects.get_or_create(call_id=call_id, defaults=fields)
    if created:
        return JsonResponse({'status': 'recorded'}, status=201)
    if all(getattr(event, name) == value for name, value in fields.items()):
        return JsonResponse({'status': 'recorded'})
    return JsonResponse({'error': 'call_event_conflict'}, status=409)


def metric_report(start_iso, end_iso):
    """Use the validated centre-panel date range, independently of its rating operator filter."""
    tz = timezone.get_default_timezone()
    start, end = date.fromisoformat(start_iso), date.fromisoformat(end_iso)
    scoped = PhoneCallMetric.objects.filter(
        occurred_at__gte=datetime.combine(start, time.min, tzinfo=tz),
        occurred_at__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz),
    )
    summary = scoped.aggregate(
        **COUNTERS, average_duration_seconds=Avg('duration_seconds', filter=Q(outcome='answered')),
    )
    days = {
        row['date']: row
        for row in scoped.annotate(date=TruncDate('occurred_at', tzinfo=tz)).values('date').annotate(**COUNTERS)
    }
    daily = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        daily.append(days.get(day, {'date': day, **dict.fromkeys(COUNTERS, 0)}))
    average = summary['average_duration_seconds']
    return {
        **summary,
        'average_duration_seconds': round(average, 1) if average is not None else None,
        'configured': bool(phone_ingest_token(TOKEN_ENV)),
        'daily': daily,
    }
