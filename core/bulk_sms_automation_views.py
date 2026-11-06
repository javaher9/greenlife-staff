import json
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .bulk_sms_views import _may_manage_bulk_sms
from .bulk_sms_automations import validate_config, preview_config, save_automation, change_automation
from .models import BulkSmsAutomation, BulkSmsParticipation, BulkSmsRecipient, BulkSmsOptOut


def serialize(item):
    return {'id': item.pk, 'name': item.name, 'status': item.status, 'config': item.config,
            'revision': item.revision, 'next_run_at': item.next_run_at.isoformat() if item.next_run_at else None,
            'last_error': item.last_error,
            'running': item.runs.filter(status='running').exists(),
            'next_step_at': item.runs.filter(status='running', next_step_at__isnull=False).order_by('next_step_at').values_list('next_step_at', flat=True).first()}


@login_required
@require_http_methods(['GET', 'POST'])
@never_cache
def automations_api(request):
    if not _may_manage_bulk_sms(request.user):
        raise PermissionDenied('مدیریت کمپین خودکار فقط برای مدیریت مجاز است.')
    if request.method == 'GET':
        items = BulkSmsAutomation.objects.filter(created_by=request.user).order_by('-id')[:200]
        return JsonResponse({'ok': True, 'automations': [serialize(x) for x in items]})
    try:
        data = json.loads(request.body)
        if not isinstance(data, dict):
            raise ValueError('درخواست معتبر نیست.')
        action = data.get('action')
        if action == 'preview':
            config = validate_config(data.get('config'))
            return JsonResponse({'ok': True, 'preview': preview_config(config)})
        if action == 'save':
            item = save_automation(user=request.user, name=data.get('name'), data=data.get('config'),
                                   item_id=data.get('id'), revision=data.get('revision'))
        elif action in ('activate', 'pause', 'end'):
            if type(data.get('revision')) is not int:
                raise ValueError('نسخه کمپین نامعتبر است؛ صفحه را تازه کنید.')
            item = change_automation(user=request.user, item_id=int(data['id']), action=action,
                                      revision=data['revision'], consent=data.get('consent') is True,
                                      typed=data.get('typed', ''))
        else:
            raise ValueError('عملیات ناشناخته است.')
        return JsonResponse({'ok': True, 'automation': serialize(item)})
    except (ValueError, TypeError, KeyError, AttributeError, UnicodeDecodeError) as exc:
        return JsonResponse({'ok': False, 'error': str(exc)[:240]}, status=400)


@login_required
@require_http_methods(['GET'])
@never_cache
def automation_report(request, pk):
    if not _may_manage_bulk_sms(request.user):
        raise PermissionDenied()
    item = get_object_or_404(BulkSmsAutomation, pk=pk, created_by=request.user)
    totals = BulkSmsRecipient.objects.filter(campaign__automation_step__run__automation=item).aggregate(
        total=Count('id'), accepted=Count('id', filter=Q(status='accepted')),
        pending=Count('id', filter=Q(status__in=['pending', 'sending'])),
        failed=Count('id', filter=Q(status='failed')), skipped=Count('id', filter=Q(status='skipped')),
    )
    rewards = BulkSmsParticipation.objects.filter(run__automation=item).aggregate(
        engaged=Count('id', filter=Q(participated_at__isnull=False)), points=Sum('points'),
    )
    runs = []
    for run in item.runs.order_by('-id').prefetch_related('steps__campaign')[:30]:
        runs.append({'id': run.pk, 'status': run.status, 'scheduled_for': run.scheduled_for,
                     'next_step_at': run.next_step_at, 'note': run.note,
                     'steps': [{'index': s.index+1, 'campaign_id': s.campaign_id,
                                'status': s.campaign.status if s.campaign else 'skipped',
                                'count': s.campaign.recipient_count if s.campaign else 0,
                                'note': s.note} for s in run.steps.all()]})
    return JsonResponse({'ok': True, 'automation': serialize(item), 'totals': totals,
                         'rewards': rewards, 'runs': runs})


@require_http_methods(['GET', 'POST'])
@never_cache
def participate(request, token):
    person = get_object_or_404(BulkSmsParticipation.objects.select_related('run__automation'), token=token)
    config = person.run.config
    expiry = person.run.created_at + timedelta(days=sum(s['delay_days'] for s in config['steps'])+30)
    available = (person.run.status != 'cancelled' and timezone.now() < expiry
                 and not BulkSmsOptOut.objects.filter(number=person.number).exists()
                 and BulkSmsRecipient.objects.filter(campaign__automation_step__run=person.run,
                      number=person.number, status='accepted').exists())
    if request.method == 'POST' and available:
        with transaction.atomic():
            person = BulkSmsParticipation.objects.select_for_update().get(pk=person.pk)
            if person.participated_at is None:
                person.participated_at = timezone.now()
                person.points = config['reward']['points'] if config['reward']['enabled'] else 0
                person.save(update_fields=['participated_at', 'points'])
    response = render(request, 'core/bulk_sms_participate.html', {
        'available': available, 'participated': person.participated_at is not None,
        'points': person.points, 'reward': config['reward'],
    })
    response['Referrer-Policy'] = 'no-referrer'
    response['X-Robots-Tag'] = 'noindex, nofollow'
    return response
