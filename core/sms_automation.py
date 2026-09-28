"""Rule-based SMS event scheduler; never sends without an enabled rule."""
from datetime import timedelta
from string import Formatter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import SmsAutomationRule, SmsScheduledMessage

TEMPLATE_FIELDS={'name','branch','date','time','amount','service','staff','phone','notes','event'}
OFFSET_LIMIT=30*24*60


def validate_template(value):
    fields={field for _,field,_,_ in Formatter().parse(value) if field}
    if not fields.issubset(TEMPLATE_FIELDS):
        raise ValueError('متغیر ناشناخته در قالب پیامک.')
    return fields


def _recipient_number(rule, patient_number='', staff_number=''):
    if rule.recipient=='patient':
        return patient_number
    if rule.recipient=='staff':
        return staff_number
    if rule.recipient=='custom':
        return rule.custom_number
    if rule.recipient=='executive':
        usernames=getattr(settings,'EXECUTIVE_USERNAMES',()) or ()
        user=get_user_model().objects.filter(username__in=usernames,profile__is_active=True).select_related('profile').first()
        return getattr(getattr(user,'profile',None),'phone','') or rule.custom_number
    if rule.recipient=='internal_manager':
        user=get_user_model().objects.filter(profile__role='internal_manager',profile__is_active=True,is_active=True).select_related('profile').first()
        return getattr(getattr(user,'profile',None),'phone','') or rule.custom_number
    return ''


def schedule_sms_event(event, event_id, *, event_at=None, patient_number='', staff_number='', context=None):
    """Idempotently enqueue an enabled event, including immediate sends.

    event_at is the actual event timestamp for before/after rules.
    A missing recipient or invalid phone never creates a queue item.
    """
    rule=SmsAutomationRule.objects.filter(event=event,is_enabled=True).first()
    if not rule or not rule.message_template:
        return None
    number=str(_recipient_number(rule,patient_number,staff_number) or '').strip()
    if len(number)!=11 or not number.startswith('09') or not number.isdigit():
        return None
    data={field:str((context or {}).get(field,'') or '') for field in TEMPLATE_FIELDS}
    try:
        validate_template(rule.message_template)
        body=rule.message_template.format_map(data).strip()
    except (ValueError,KeyError,IndexError):
        return None
    if not body:
        return None
    anchor=event_at or timezone.now()
    if timezone.is_naive(anchor):
        anchor=timezone.make_aware(anchor,timezone.get_current_timezone())
    offset=rule.offset*{'minutes':1,'hours':60,'days':1440}[rule.offset_unit]
    if offset>OFFSET_LIMIT:
        return None
    if rule.timing=='before':
        due_at=anchor-timedelta(minutes=offset)
    elif rule.timing=='after':
        due_at=anchor+timedelta(minutes=offset)
    else:
        due_at=timezone.now()
    record,_=SmsScheduledMessage.objects.get_or_create(
        event_key=f'{event}:{event_id}:{rule.recipient}',
        defaults={'rule':rule,'number':number,'body':body,'due_at':due_at},
    )
    return record


def process_due_sms(batch_size=25):
    """Claim and process due messages; caller must run periodically."""
    from .sms import SmsGatewayError,send_sms

    processed=0
    for _ in range(batch_size):
        with transaction.atomic():
            item=(SmsScheduledMessage.objects.select_for_update(skip_locked=True)
                  .filter(status='pending',due_at__lte=timezone.now())
                  .order_by('due_at','id').first())
            if not item:
                break
            item.status='sending'
            item.attempt_count+=1
            item.save(update_fields=['status','attempt_count','updated_at'])
        try:
            send_sms(item.number,item.body,purpose='manual')
        except (SmsGatewayError,Exception) as exc:
            item.status='failed'
            item.error=str(exc)[:300]
        else:
            item.status='accepted'
            item.error=''
        item.save(update_fields=['status','error','updated_at'])
        processed+=1
    return processed
