"""Private IVR rating intake and aggregation for the phone control panel."""
from datetime import date, datetime, time, timedelta
import json

from django.db.models import Avg, Count, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .call_center_identity import call_center_display_name
from .models import EmployeeProfile
from .phone_ingestion import authorized_feeder, opaque_call_id, phone_ingest_token
from .phone_rating_models import PhoneCallRating


SCORES = range(1, 6)
MAX_REPORT_DAYS = 90
MAX_OPERATOR_ID = 2 ** 63 - 1
TOKEN_ENV = 'STAFF_PHONE_RATINGS_TOKEN'


def _active_call_center():
    return Q(role='call_center', is_active=True, user__is_active=True)


def _payload(body):
    data = json.loads(body)
    if not isinstance(data, dict) or data.keys() != {'call_id', 'operator_id', 'score'}:
        raise ValueError
    call_id = opaque_call_id(data['call_id'])
    operator_id, score = data['operator_id'], data['score']
    if (
        type(operator_id) is not int or not 0 < operator_id <= MAX_OPERATOR_ID
        or type(score) is not int or score not in SCORES
    ):
        raise ValueError
    return call_id, operator_id, score


@csrf_exempt
@never_cache
@require_POST
def ingest_rating(request):
    """Accept an authenticated, privacy-minimal rating from the configured IVR."""
    token = phone_ingest_token(TOKEN_ENV)
    if not token:
        return JsonResponse({'error': 'intake_unavailable'}, status=503)

    if not authorized_feeder(request, token):
        return JsonResponse({'error': 'authorization_required'}, status=401)
    if request.content_type != 'application/json':
        return JsonResponse({'error': 'unsupported_media_type'}, status=415)
    if len(request.body) > 1024:
        return JsonResponse({'error': 'invalid_rating'}, status=400)

    try:
        call_id, operator_id, score = _payload(request.body)
    except (ValueError, UnicodeError, RecursionError):
        return JsonResponse({'error': 'invalid_rating'}, status=400)

    rating = PhoneCallRating.objects.filter(call_id=call_id).first()
    if rating is None:
        if not EmployeeProfile.objects.filter(_active_call_center(), pk=operator_id).exists():
            return JsonResponse({'error': 'invalid_operator'}, status=400)
        rating, created = PhoneCallRating.objects.get_or_create(
            call_id=call_id,
            defaults={'operator_id': operator_id, 'score': score},
        )
        if created:
            return JsonResponse({'status': 'recorded'}, status=201)

    if rating.operator_id == operator_id and rating.score == score:
        return JsonResponse({'status': 'recorded'})
    return JsonResponse({'error': 'rating_conflict'}, status=409)


def _rating_dates(params, today):
    default_start = today - timedelta(days=6)
    try:
        start = date.fromisoformat(params['start']) if params.get('start') else default_start
        end = date.fromisoformat(params['end']) if params.get('end') else today
    except (TypeError, ValueError):
        return default_start, today, 'تاریخ شروع و پایان را بررسی کنید.'
    if end < start or end > today or (end - start).days >= MAX_REPORT_DAYS:
        return default_start, today, 'بازهٔ زمانی باید حداکثر ۹۰ روز و تا امروز باشد.'
    return start, end, ''


def _average(value):
    return round(value, 2) if value is not None else None


def rating_report(params):
    """Summarize stored customer scores by Tehran day and call-center operator."""
    tz = timezone.get_default_timezone()
    today = timezone.localdate(timezone=tz)
    start, end, error = _rating_dates(params, today)
    scoped = PhoneCallRating.objects.filter(
        rated_at__gte=datetime.combine(start, time.min, tzinfo=tz),
        rated_at__lt=datetime.combine(end + timedelta(days=1), time.min, tzinfo=tz),
    )
    rated_operator_ids = scoped.values('operator_id')
    profiles = EmployeeProfile.objects.filter(
        _active_call_center() | Q(pk__in=rated_operator_ids),
    ).select_related('user')
    operators = {profile.pk: call_center_display_name(profile) for profile in profiles}

    operator_id = None
    if params.get('operator'):
        try:
            selected = int(params['operator'])
        except (TypeError, ValueError):
            selected = None
        if selected in operators:
            operator_id = selected
            scoped = scoped.filter(operator_id=operator_id)
        else:
            error = 'اپراتور انتخاب‌شده در این بازه در دسترس نیست.'
            scoped = scoped.none()

    summary = scoped.aggregate(count=Count('pk'), average=Avg('score'))
    # The range is bounded so even unreported days are visible in the chart.
    days_with_scores = {
        row['day']: row
        for row in scoped.annotate(day=TruncDate('rated_at', tzinfo=tz)).values('day').annotate(
            count=Count('pk'), average=Avg('score'),
        )
    }
    daily = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        row = days_with_scores.get(day, {})
        daily.append({'date': day, 'count': row.get('count', 0), 'average': _average(row.get('average'))})

    counts = dict(scoped.values_list('score').annotate(total=Count('pk')))
    total = summary['count']
    operator_rows = scoped.values('operator_id').annotate(
        count=Count('pk'), average=Avg('score'),
    ).order_by('-count', 'operator_id')

    return {
        'configured': bool(phone_ingest_token(TOKEN_ENV)),
        'start': start.isoformat(),
        'end': end.isoformat(),
        'operator': str(operator_id) if operator_id is not None else '',
        'operators': [
            {'id': str(pk), 'name': name} for pk, name in sorted(operators.items(), key=lambda pair: pair[1])
        ],
        'count': total,
        'average': _average(summary['average']),
        'distribution': [
            {
                'score': score,
                'count': counts.get(score, 0),
                'percentage': round(counts.get(score, 0) * 100 / total, 1) if total else 0,
            }
            for score in SCORES
        ],
        'daily': daily,
        'by_operator': [
            {
                'id': row['operator_id'],
                'name': operators.get(row['operator_id'], 'اپراتور حذف‌شده'),
                'count': row['count'],
                'average': _average(row['average']),
            }
            for row in operator_rows
        ],
        'error': error,
    }
