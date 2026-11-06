"""Schedule bulk campaigns without gateway calls; the existing worker dispatches.

All mutations lock the definition before its runs. Each scheduled run and step
is unique, and queued recipients still pass suppression/cooldown at dispatch.
"""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db import transaction
from django.db.models import Q, Max
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .bulk_sms_audiences import audience_preview, catalog, _iran_number
from .bulk_sms_dispatch import _assert_gateway, _gateway_active, COOLDOWN_DAYS, MAX_DAILY_ATTEMPTS
from .models import (
    BulkSmsAutomation, BulkSmsAutomationRun, BulkSmsAutomationStep, BulkSmsParticipation,
    BulkSmsCampaign, BulkSmsRecipient, BulkSmsOptOut, VisitAppointment,
)

TEHRAN = ZoneInfo('Asia/Tehran')


def date_value(value):
    try:
        result = parse_datetime(str(value))
        if result is None:
            raise ValueError()
        if timezone.is_naive(result):
            result = timezone.make_aware(result, TEHRAN)
        return result.astimezone(TEHRAN)
    except (ValueError, TypeError, OverflowError):
        raise ValueError('تاریخ و ساعت معتبر وارد کنید؛ زمان‌بندی به وقت تهران است.')


def validate_config(data):
    if not isinstance(data, dict):
        raise ValueError('تنظیمات کمپین معتبر نیست.')
    available = {x['key'] for x in catalog()}
    keys = data.get('segments')
    if not isinstance(keys, list) or not 1 <= len(keys) <= 80 or any(not isinstance(x, str) or x not in available for x in keys):
        raise ValueError('حداقل یک گروه معتبر انتخاب کنید.')
    if len(set(keys)) != len(keys) or data.get('combine', 'any') not in ('any', 'all'):
        raise ValueError('ترکیب گروه‌ها معتبر نیست.')
    exits = data.get('exclude_segments', [])
    if not isinstance(exits, list) or len(exits) > 20 or any(not isinstance(x, str) or x not in available for x in exits):
        raise ValueError('گروه‌های خروج معتبر نیستند.')
    start = date_value(data.get('start_at'))
    end = date_value(data['end_at']) if data.get('end_at') else None
    if end and end <= start:
        raise ValueError('پایان کمپین باید بعد از شروع باشد.')
    interval = data.get('interval_days', 0)
    limit = data.get('limit', 100)
    daily = data.get('daily_limit', 100)
    inactive = data.get('inactive_days', 0)
    if type(interval) is not int or interval not in (0, 7, 14, 30):
        raise ValueError('تکرار زمان‌بندی معتبر نیست.')
    if type(limit) is not int or not 1 <= limit <= 2500 or type(daily) is not int or not 1 <= daily <= MAX_DAILY_ATTEMPTS:
        raise ValueError('سقف هر اجرا ۲۵۰۰ و سقف روزانه حداکثر ۴۰۰ شماره است.')
    if type(inactive) is not int or inactive not in (0, 30, 60, 90, 180):
        raise ValueError('بازه عدم مراجعه معتبر نیست.')
    reward = data.get('reward') or {}
    if not isinstance(reward, dict):
        raise ValueError('تنظیمات امتیاز معتبر نیست.')
    points = reward.get('points', 0) if reward.get('enabled') is True else 0
    if type(points) is not int or not 0 <= points <= 10000:
        raise ValueError('امتیاز باید بین ۰ و ۱۰۰۰۰ باشد.')
    title = str(reward.get('title', '')).strip()
    if len(title) > 120:
        raise ValueError('عنوان هدیه بیش از حد طولانی است.')
    steps = data.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 3:
        raise ValueError('یک تا سه مرحله پیام تعریف کنید.')
    clean_steps = []
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise ValueError('مرحله پیام معتبر نیست.')
        body = step.get('body', '')
        delay = step.get('delay_days', 0)
        condition = step.get('condition', 'all')
        if not isinstance(body, str) or not 3 <= len(body.strip()) <= 430:
            raise ValueError('متن هر مرحله باید بین ۳ تا ۴۳۰ نویسه باشد.')
        if type(delay) is not int or (index == 0 and delay != 0) or (index > 0 and not 7 <= delay <= 90):
            raise ValueError('فاصله مراحل بعدی باید حداقل ۷ و حداکثر ۹۰ روز باشد.')
        if condition not in ('all', 'unengaged', 'engaged') or (index == 0 and condition != 'all'):
            raise ValueError('شرط مرحله معتبر نیست.')
        clean_steps.append({'body': body.strip(), 'delay_days': delay, 'condition': condition})
        final_body = body.replace('{لینک}', settings.PUBLIC_BASE_URL.rstrip('/')+'/s/c/'+'0'*36+'/').replace('{امتیاز}',str(points)).replace('{هدیه}',title)
        if len(final_body+'\nلغو 11') > 600:
            raise ValueError('متن نهایی با لینک و هدیه از ۶۰۰ نویسه بیشتر است؛ متن را کوتاه کنید.')
    engagement = reward.get('enabled') is True or any(s['condition'] != 'all' for s in clean_steps)
    if engagement and '{لینک}' not in clean_steps[0]['body']:
        raise ValueError('برای ثبت مشارکت یا امتیاز، {لینک} را در متن مرحله اول قرار دهید.')
    duration = sum(s['delay_days'] for s in clean_steps)
    if interval and interval < duration + COOLDOWN_DAYS:
        raise ValueError('فاصله تکرار باید دست‌کم ۷ روز بیشتر از مجموع فاصله مراحل باشد.')
    if end and start + timedelta(days=duration) >= end:
        raise ValueError('تاریخ پایان باید پس از آخرین مرحله باشد.')
    return {
        'scenario': str(data.get('scenario', 'custom'))[:32], 'segments': keys,
        'combine': data.get('combine', 'any'), 'exclude_segments': exits,
        'inactive_days': inactive, 'start_at': start.isoformat(),
        'end_at': end.isoformat() if end else None, 'interval_days': interval,
        'limit': limit, 'daily_limit': daily, 'steps': clean_steps,
        'reward': {'enabled': reward.get('enabled') is True, 'points': points, 'title': title},
    }


def eligible_numbers(config, *, now=None, suppress=True):
    now = now or timezone.now()
    with timezone.override(TEHRAN):
        result = audience_preview(config['segments'], combine=config['combine'], include_numbers=True)
        if result['truncated']:
            raise ValueError('گروه بیش از حد بزرگ است؛ گروه‌های محدودتری انتخاب کنید.')
        numbers = set(result['_numbers'])
        if config['exclude_segments']:
            excluded = audience_preview(config['exclude_segments'], include_numbers=True)
            if excluded['truncated']:
                raise ValueError('گروه خروج بیش از حد بزرگ است؛ گروه خروج محدودتری انتخاب کنید.')
            numbers.difference_update(excluded['_numbers'])
    if config['inactive_days']:
        # Require an actual past visit and no more recent attended visit.
        cutoff = timezone.localdate(now, TEHRAN) - timedelta(days=config['inactive_days'])
        old, recent = set(), set()
        for phone, day in VisitAppointment.objects.filter(status__in=['arrived', 'completed']).values_list('phone', 'appointment_date').iterator():
            number = _iran_number(phone)
            if number:
                (old if day < cutoff else recent).add(number)
        numbers.intersection_update(old - recent)
    if suppress:
        numbers.difference_update(BulkSmsOptOut.objects.values_list('number', flat=True))
        numbers.difference_update(BulkSmsRecipient.objects.filter(
            status__in=['accepted', 'sending'], attempted_at__gte=now-timedelta(days=COOLDOWN_DAYS),
        ).values_list('number', flat=True))
        numbers.difference_update(BulkSmsRecipient.objects.filter(
            status='pending', campaign__status__in=['queued', 'paused'],
        ).values_list('number', flat=True))
    return sorted(numbers), result['count']


def preview_config(config):
    numbers, total = eligible_numbers(config)
    return {'matched': total, 'eligible': len(numbers), 'count': min(len(numbers), config['limit']),
            'excluded': total-len(numbers), 'limited': max(0, len(numbers)-config['limit'])}


def save_automation(*, user, name, data, item_id=None, revision=None):
    config = validate_config(data)
    if not isinstance(name, str) or not 2 <= len(name.strip()) <= 100:
        raise ValueError('نام کمپین باید بین ۲ تا ۱۰۰ نویسه باشد.')
    with transaction.atomic():
        if item_id:
            item = BulkSmsAutomation.objects.select_for_update().filter(pk=item_id, created_by=user).first()
            if not item or item.revision != revision:
                raise ValueError('کمپین تغییر کرده است؛ صفحه را تازه کنید.')
            if item.status == 'active' or item.runs.filter(status='running').exists():
                raise ValueError('برای ویرایش مراحل، ابتدا کمپین و اجراهای باقیمانده را پایان دهید.')
            item.revision += 1
        else:
            item = BulkSmsAutomation(created_by=user)
        item.name, item.config, item.status = name.strip(), config, 'draft'
        item.next_run_at, item.consent_at, item.last_error = None, None, ''
        item.save()
        return item


def change_automation(*, user, item_id, action, revision=None, consent=False, typed=''):
    with transaction.atomic():
        item = BulkSmsAutomation.objects.select_for_update().filter(pk=item_id, created_by=user).first()
        if not item or (revision is not None and item.revision != revision):
            raise ValueError('کمپین در دسترس نیست یا تغییر کرده است؛ صفحه را تازه کنید.')
        now = timezone.now()
        if action == 'activate':
            if item.status not in ('draft', 'paused'):
                raise ValueError('کمپین در وضعیت قابل فعال‌سازی نیست.')
            if not consent or typed != 'تایید':
                raise ValueError('رضایت مخاطبان و عبارت «تایید» را تأیید کنید.')
            _assert_gateway()
            config = validate_config(item.config)
            if config['end_at'] and date_value(config['end_at']) <= now:
                raise ValueError('تاریخ پایان گذشته است؛ زمان‌بندی جدید تعریف کنید.')
            if item.status == 'draft':
                if date_value(config['start_at']) <= now:
                    raise ValueError('زمان شروع باید در آینده باشد.')
                item.next_run_at = date_value(config['start_at'])
            item.status, item.consent_at, item.last_error = 'active', now, ''
            for step in BulkSmsAutomationStep.objects.filter(run__automation=item, paused_by_automation=True).select_related('campaign'):
                if step.campaign and step.campaign.status == 'paused':
                    BulkSmsCampaign.objects.filter(pk=step.campaign_id, status='paused').update(status='queued')
                step.paused_by_automation = False
                step.save(update_fields=['paused_by_automation'])
        elif action in ('pause', 'end'):
            if item.status not in ('active', 'paused', 'draft'):
                raise ValueError('کمپین قبلاً پایان یافته است.')
            if action == 'pause' and item.status != 'active':
                raise ValueError('فقط کمپین فعال قابل توقف است.')
            item.status = 'paused' if action == 'pause' else 'ended'
            for step in BulkSmsAutomationStep.objects.filter(run__automation=item, campaign__status__in=['queued', 'paused']).select_related('campaign'):
                if action == 'pause' and step.campaign.status == 'queued':
                    BulkSmsCampaign.objects.filter(pk=step.campaign_id, status='queued').update(status='paused')
                    step.paused_by_automation = True
                    step.save(update_fields=['paused_by_automation'])
                elif action == 'end':
                    BulkSmsCampaign.objects.filter(pk=step.campaign_id).update(status='cancelled')
                    BulkSmsRecipient.objects.filter(campaign_id=step.campaign_id, status='pending').update(status='skipped', reason='پایان سناریوی خودکار')
            if action == 'end':
                item.next_run_at = None
                item.runs.filter(status='running').update(status='cancelled', next_step_at=None)
        else:
            raise ValueError('دستور نامعتبر است.')
        item.revision += 1
        item.save()
        return item


def _next_occurrence(config, previous, now):
    interval = config['interval_days']
    if not interval:
        return None
    # Missed recurrences are skipped, never replayed in a burst.
    elapsed = max(1, (now - previous).days // interval + 1)
    result = previous + timedelta(days=interval * elapsed)
    if config['end_at'] and result >= date_value(config['end_at']):
        return None
    return result


def _queue_step(run, now):
    config, index = run.config, run.next_step
    previous = run.steps.order_by('-index').select_related('campaign').first()
    if previous and previous.campaign and BulkSmsRecipient.objects.filter(campaign=previous.campaign, status__in=['pending', 'sending']).exists():
        return  # Wait for the previous queue; never overtake it.
    if index >= len(config['steps']):
        run.status, run.next_step_at = 'completed', None
        run.save(update_fields=['status', 'next_step_at'])
        return
    if previous and previous.campaign:
        last_attempt = BulkSmsRecipient.objects.filter(campaign=previous.campaign).aggregate(value=Max('attempted_at'))['value']
        if last_attempt:
            safe_due = last_attempt + timedelta(days=config['steps'][index]['delay_days'])
            if run.next_step_at < safe_due:
                run.next_step_at = safe_due
                run.save(update_fields=['next_step_at'])
    if run.next_step_at > now:
        return
    numbers, total = eligible_numbers(config, now=now)
    if index:
        condition = config['steps'][index]['condition']
        people = run.participants.all()
        if condition == 'engaged':
            people = people.filter(participated_at__isnull=False)
        elif condition == 'unengaged':
            people = people.filter(participated_at__isnull=True)
        # Follow-ups are restricted to recipients who actually received stage 1.
        initial = run.steps.get(index=0)
        delivered = set(BulkSmsRecipient.objects.filter(campaign_id=initial.campaign_id, status='accepted').values_list('number', flat=True)) if initial.campaign_id else set()
        numbers = sorted(set(numbers) & set(people.values_list('number', flat=True)) & delivered)
    numbers = numbers[:config['limit']]
    step = BulkSmsAutomationStep.objects.create(run=run, index=index)
    if numbers:
        if index == 0:
            BulkSmsParticipation.objects.bulk_create([BulkSmsParticipation(run=run, number=n) for n in numbers], batch_size=400)
        body = config['steps'][index]['body']
        if 'لغو 11' not in body:
            body += '\nلغو 11'
        campaign = BulkSmsCampaign.objects.create(
            created_by=run.automation.created_by, body=body, segments=config['segments'],
            combine=config['combine'], recipient_count=len(numbers), excluded_count=max(0, total-len(numbers)),
            consent_attested=True, status='queued', approved_at=now,
        )
        BulkSmsRecipient.objects.bulk_create([BulkSmsRecipient(campaign=campaign, number=n) for n in numbers], batch_size=400)
        step.campaign = campaign
    else:
        step.note = 'مخاطب واجد شرایط برای این مرحله وجود نداشت.'
    step.save()
    run.next_step += 1
    run.next_step_at = now + timedelta(days=config['steps'][run.next_step]['delay_days']) if run.next_step < len(config['steps']) else None
    if not numbers and index == 0:
        run.status, run.next_step_at = 'skipped', None
        run.note = step.note
    run.save()


def process_due_automations(limit=10):
    if not _gateway_active():
        return 0
    now = timezone.now()
    ids = list(BulkSmsAutomation.objects.filter(status='active').filter(
        Q(next_run_at__lte=now) | Q(runs__status='running'),
    ).order_by('updated_at', 'id').distinct().values_list('id', flat=True)[:limit])
    for pk in ids:
        with transaction.atomic():
            item = BulkSmsAutomation.objects.select_for_update(skip_locked=True).filter(pk=pk, status='active').first()
            if not item:
                continue
            from .bulk_sms_views import _may_manage_bulk_sms
            if not _may_manage_bulk_sms(item.created_by):
                change_automation(user=item.created_by, item_id=pk, action='pause')
                continue
            if item.config['end_at'] and date_value(item.config['end_at']) <= now:
                change_automation(user=item.created_by, item_id=pk, action='end')
                continue
            try:
                with transaction.atomic():
                    for run in item.runs.filter(status='running').select_related('automation'):
                        _queue_step(run, now)
                    if item.next_run_at and item.next_run_at <= now and not item.runs.filter(status='running').exists():
                        run, created = BulkSmsAutomationRun.objects.get_or_create(
                            automation=item, scheduled_for=item.next_run_at,
                            defaults={'config': item.config, 'next_step_at': now},
                        )
                        if created:
                            _queue_step(run, now)
                        item.next_run_at = _next_occurrence(item.config, item.next_run_at, now)
                    if item.next_run_at is None and not item.runs.filter(status='running').exists():
                        item.status = 'ended'
                    item.last_error = ''
                    item.save()
            except ValueError as exc:
                change_automation(user=item.created_by, item_id=pk, action='pause')
                BulkSmsAutomation.objects.filter(pk=pk).update(last_error=str(exc)[:240])
    return len(ids)


def automation_dispatch_context(campaign_id, now, cache):
    """Re-evaluate membership once per campaign per worker batch, before send."""
    if campaign_id in cache:
        return cache[campaign_id]
    step = BulkSmsAutomationStep.objects.filter(campaign_id=campaign_id).select_related('run__automation').first()
    if not step:
        cache[campaign_id] = None
        return None
    run, item = step.run, step.run.automation
    from .bulk_sms_views import _may_manage_bulk_sms
    allowed = item.status == 'active' and _may_manage_bulk_sms(item.created_by)
    if run.config['end_at'] and now >= date_value(run.config['end_at']):
        allowed = False
    try:
        numbers = set(eligible_numbers(run.config, now=now, suppress=False)[0]) if allowed else set()
    except ValueError:
        numbers = set()
    condition = run.config['steps'][step.index]['condition']
    people = run.participants.all()
    if condition == 'engaged':
        people = people.filter(participated_at__isnull=False)
    elif condition == 'unengaged':
        people = people.filter(participated_at__isnull=True)
    numbers.intersection_update(people.values_list('number', flat=True))
    recent = BulkSmsRecipient.objects.filter(campaign__automation_step__run__automation=item, attempted_at__gte=now-timedelta(hours=24)).count()
    cache[campaign_id] = {'step': step, 'numbers': numbers, 'remaining': max(0, run.config['daily_limit']-recent)}
    return cache[campaign_id]


def personalized_body(body, context, number):
    if context is None:
        return body
    run = context['step'].run
    person = BulkSmsParticipation.objects.get(run=run, number=number)
    url = settings.PUBLIC_BASE_URL.rstrip('/') + reverse('bulk_sms_participate', args=[person.token])
    reward = run.config['reward']
    result = body.replace('{لینک}', url).replace('{امتیاز}', str(reward['points'])).replace('{هدیه}', reward['title'])
    if len(result) > 600:
        raise ValueError('متن نهایی با لینک و هدیه بیشتر از ۶۰۰ نویسه است.')
    return result
