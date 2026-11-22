"""Management planning for consented callbacks, with no outbound transport."""

import json

from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Case, CharField, Count, Exists, F, OuterRef, Value, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast, Substr
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from .assistant_queue_models import (
    ASSISTANT_CHOICES, OPEN_ASSISTANT_JOB_STATES, AssistantCallJob, AssistantCallQueue,
)
from .models import AuditLog, LeadCallSession, ReferralLead
from .phone_center_views import can_access_phone_center


ASSISTANTS = dict(ASSISTANT_CHOICES)
JOB_LABELS = {**dict(AssistantCallJob.STATUS_CHOICES), 'blocked': 'رضایت یا موعد نیاز به بررسی دارد'}


def _can_manage(user):
    profile = getattr(user, 'profile', None)
    return user.is_superuser or bool(profile and profile.is_active and profile.role == 'admin')


def _eligible_consent():
    # Finalized consent is normalized to a local ISO timestamp by the call plaque.
    # A different date or time in the live agenda requires an updated consent snapshot.
    followup = KeyTextTransform('followup_at', 'data')
    return LeadCallSession.objects.filter(
        state='final',
        data__outcome='follow_up',
        data__followup_consent='yes',
        data__do_not_contact=False,
        lead__call_profile__latest_session_id=F('pk'),
        lead__call_profile__do_not_contact=False,
        lead__contact_result='follow_up',
    ).exclude(
        lead__status__in=('won', 'lost', 'visited'),
    ).exclude(
        lead__phone='',
    ).alias(
        consent_day=Substr(followup, 1, 10),
        consent_time=Substr(followup, 12, 8),
    ).filter(
        consent_day=Cast('lead__next_follow_up', CharField()),
        consent_time=Substr(Cast('lead__next_follow_up_time', CharField()), 1, 8),
    )


def _page(queryset, number):
    page = Paginator(queryset, 25).get_page(number)
    return {'items': list(page.object_list), 'page': page.number,
            'pages': page.paginator.num_pages, 'total': page.paginator.count}


def _queue_payload(request):
    eligible = _eligible_consent()
    jobs = AssistantCallJob.objects.alias(
        consent_valid=Exists(eligible.filter(pk=OuterRef('consent_session_id'), lead_id=OuterRef('lead_id'))),
    ).annotate(
        effective_status=Case(
            When(status__in=OPEN_ASSISTANT_JOB_STATES, consent_valid=False, then=Value('blocked')),
            default=F('status'),
        ),
    )
    counts = {
        (row['queue_id'], row['effective_status']): row['total']
        for row in jobs.values('queue_id', 'effective_status').annotate(total=Count('pk'))
    }
    paused = dict(AssistantCallQueue.objects.values_list('assistant', 'paused'))
    queues = [
        {
            'assistant': assistant,
            'name': name,
            'paused': paused.get(assistant, False),
            **{f'{status}_count': counts.get((assistant, status), 0) for status in JOB_LABELS},
        }
        for assistant, name in ASSISTANT_CHOICES
    ]

    assistant = request.GET.get('assistant', '')
    if assistant in ASSISTANTS:
        jobs = jobs.filter(queue_id=assistant)
    status = request.GET.get('status', '')
    if status in JOB_LABELS:
        jobs = jobs.filter(effective_status=status)
    page = _page(jobs.order_by('-created_at', '-pk').values(
        'id', 'scheduled_for', 'attempts',
        assistant=F('queue_id'), lead_name=F('lead__full_name'), state=F('effective_status'),
    ), request.GET.get('page'))
    for item in page['items']:
        item['status'] = item.pop('state')
        item['status_label'] = JOB_LABELS[item['status']]
        item['scheduled_for'] = timezone.localtime(item['scheduled_for']).isoformat()

    open_jobs = AssistantCallJob.objects.filter(lead_id=OuterRef('lead_id'), status__in=OPEN_ASSISTANT_JOB_STATES)
    candidates = eligible.filter(assistant_call_job__isnull=True).exclude(
        Exists(open_jobs),
    ).order_by(
        'lead__next_follow_up', 'lead__next_follow_up_time', 'pk',
    ).values(
        'lead_id', name=F('lead__full_name'), scheduled_for=KeyTextTransform('followup_at', 'data'),
    )
    return {
        'can_manage': _can_manage(request.user),
        'automatic_dispatch': False,
        'queues': queues,
        'jobs': page,
        'candidates': _page(candidates, request.GET.get('candidate_page')),
    }


def _audit(request, action, target, object_id, **metadata):
    AuditLog.objects.create(
        actor=request.user, action='assistant_queue_' + action, path=request.path, method='POST',
        object_type=target, object_id=str(object_id), metadata=metadata,
    )


def _error(message, status=400):
    return JsonResponse({'ok': False, 'error': message}, status=status)


def _valid_id(value):
    return type(value) is int and 0 < value < 2**63


def _enqueue(request, assistant, lead_id):
    # The call plaque serializes consent changes using the same lead row lock.
    lead = ReferralLead.objects.select_for_update().filter(pk=lead_id).only('id').first()
    if not lead:
        return _error('درخواست پیگیری واجد شرایط پیدا نشد.', status=409)
    consent = _eligible_consent().filter(lead=lead).values_list(
        'pk', 'data__followup_at',
    ).first()
    if not consent:
        return _error('رضایت یا موعد پیگیری تغییر کرده است. فهرست را تازه کنید.', status=409)
    consent_id, timestamp = consent
    try:
        scheduled_for = parse_datetime(timestamp) if isinstance(timestamp, str) else None
    except ValueError:
        scheduled_for = None
    if not scheduled_for or timezone.is_naive(scheduled_for):
        return _error('موعد ثبت‌شده نیاز به بررسی دارد.', status=409)
    existing = AssistantCallJob.objects.filter(consent_session_id=consent_id).first()
    if existing and existing.queue_id == assistant and existing.status == 'queued':
        return JsonResponse({'ok': True})
    if existing or AssistantCallJob.objects.filter(lead=lead, status__in=OPEN_ASSISTANT_JOB_STATES).exists():
        return _error('این درخواست قبلاً به صف اضافه شده است.', status=409)
    queue, _ = AssistantCallQueue.objects.get_or_create(assistant=assistant)
    job = AssistantCallJob.objects.create(
        queue=queue, lead=lead, consent_session_id=consent_id,
        scheduled_for=scheduled_for, created_by=request.user,
    )
    _audit(request, 'enqueue', 'AssistantCallJob', job.pk, assistant=assistant, consent_id=consent_id)
    return JsonResponse({'ok': True})


def _set_paused(request, assistant, paused):
    queue, _ = AssistantCallQueue.objects.select_for_update().get_or_create(assistant=assistant)
    if queue.paused != paused:
        queue.paused = paused
        queue.save(update_fields=('paused', 'updated_at'))
        _audit(request, 'pause' if paused else 'resume', 'AssistantCallQueue', assistant)
    return JsonResponse({'ok': True})


def _cancel(request, job_id):
    job = AssistantCallJob.objects.select_for_update().filter(pk=job_id).first()
    if not job:
        return _error('درخواست در صف پیدا نشد.', status=404)
    if job.status == 'cancelled':
        return JsonResponse({'ok': True})
    if job.status not in OPEN_ASSISTANT_JOB_STATES:
        return _error('وضعیت درخواست دیگر قابل لغو نیست.', status=409)
    job.status = 'cancelled'
    job.save(update_fields=('status', 'updated_at'))
    _audit(request, 'cancel', 'AssistantCallJob', job.pk, assistant=job.queue_id)
    return JsonResponse({'ok': True})


@login_required
@require_http_methods(['GET', 'POST'])
@never_cache
@csrf_protect
def assistant_queue(request):
    if not can_access_phone_center(request.user):
        return _error('دسترسی مجاز نیست.', status=403)
    if request.method == 'GET':
        return JsonResponse(_queue_payload(request))
    if not _can_manage(request.user):
        return _error('تغییر صف به دسترسی مدیر نیاز دارد.', status=403)
    if request.content_type != 'application/json' or len(request.body) > 4096:
        return _error('درخواست معتبر نیست.')
    try:
        body = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return _error('درخواست معتبر نیست.')
    if not isinstance(body, dict):
        return _error('درخواست معتبر نیست.')
    action, assistant = body.get('action'), body.get('assistant')
    try:
        with transaction.atomic():
            if action == 'cancel' and _valid_id(body.get('job_id')):
                return _cancel(request, body['job_id'])
            if isinstance(assistant, str) and assistant in ASSISTANTS:
                if action in ('pause', 'resume'):
                    return _set_paused(request, assistant, action == 'pause')
                if action == 'enqueue' and _valid_id(body.get('lead_id')):
                    return _enqueue(request, assistant, body['lead_id'])
    except IntegrityError:
        return _error('صف هم‌زمان تغییر کرده است. فهرست را تازه کنید.', status=409)
    return _error('عملیات صف یا شناسه معتبر نیست.')
