"""Rule-based SMS event scheduler; never sends without an enabled rule."""
from datetime import timedelta
from string import Formatter

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from .models import SmsAutomationRule, SmsScheduledMessage

TEMPLATE_FIELDS={'name','branch','address','date','time','amount','service','staff','phone','notes','event','username','login_url'}
OFFSET_LIMIT=30*24*60


def sms_staff_display_name(user):
    """Patient-facing staff name.

    Call-center staff must always be identified by their configured flower name.
    Other roles keep their normal staff name.
    """
    if not user:
        return ''
    profile=getattr(user,'profile',None)
    if profile and getattr(profile,'role','')=='call_center':
        from .call_center_identity import call_center_display_name
        return call_center_display_name(user)
    return user.get_full_name() or user.username



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



# Map the app's actual persisted call outcomes to independently configurable rules.
CALL_RESULT_SMS_EVENTS={
    'no_answer':'call_no_answer',
    'not_interested':'call_not_interested',
    'follow_up':'call_follow_up',
    'appointment':'call_appointment',
}
CALL_EVENT_RESULTS={event:result for result,event in CALL_RESULT_SMS_EVENTS.items()}
CALL_EVENT_STATUSES={
    'no_answer':'contacted',
    'not_interested':'lost',
    'follow_up':'contacted',
    'appointment':'appointment',
}


def queue_call_result_sms(lead_id):
    """Replace stale pending messages after a saved call outcome; never send on dial."""
    from .models import ReferralLead
    lead=ReferralLead.objects.select_related('assigned_to__user','assigned_to__branch').filter(pk=lead_id).first()
    if not lead:
        return None
    # A subsequent result supersedes all older pending messages for this lead.
    SmsScheduledMessage.objects.filter(
        rule__event__in=tuple(CALL_EVENT_RESULTS),
        event_key__contains=f':{lead.pk}-',
        status='pending',
    ).update(status='cancelled')
    event=CALL_RESULT_SMS_EVENTS.get(lead.contact_result)
    if not event or lead.status!=CALL_EVENT_STATUSES[lead.contact_result]:
        return None
    assigned=lead.assigned_to
    user=assigned.user if assigned else None
    stamp=lead.updated_at.strftime('%Y%m%d%H%M%S%f')
    return schedule_sms_event(
        event,f'{lead.pk}-{stamp}',patient_number=lead.phone,
        staff_number=getattr(assigned,'phone','') if assigned else '',
        context={
            'name':lead.full_name,'phone':lead.phone,
            'service':lead.interested_service,
            'staff':sms_staff_display_name(user),
            'branch':assigned.branch.name if assigned and assigned.branch else '',
            'notes':lead.notes,'event':lead.get_contact_result_display(),
        },
    )


def _current_call_outcome(item):
    """Prevent a delayed call SMS from dispatching after the lead has changed."""
    from .models import ReferralLead
    expected=CALL_EVENT_RESULTS.get(item.rule.event)
    if not expected:
        return True
    prefix=f'{item.rule.event}:'
    if not item.event_key.startswith(prefix):
        return False
    lead_token=item.event_key[len(prefix):].split(':',1)[0]
    lead_id=lead_token.split('-',1)[0]
    if not lead_id.isdigit():
        return False
    return ReferralLead.objects.filter(
        pk=int(lead_id),contact_result=expected,
        status=CALL_EVENT_STATUSES[expected],
    ).exists()


def process_due_sms(batch_size=25):
    """Claim and process due messages; caller must run periodically.

    A worker can be terminated after claiming an item. Reclaim old "sending"
    leases so those messages cannot remain stuck forever.
    """
    from .sms import SmsGatewayError,send_sms

    lease_cutoff=timezone.now()-timedelta(minutes=5)
    SmsScheduledMessage.objects.filter(
        status='sending',updated_at__lt=lease_cutoff,attempt_count__lt=4,
    ).update(status='pending',error='بازیابی خودکار پس از توقف worker')
    SmsScheduledMessage.objects.filter(
        status='sending',updated_at__lt=lease_cutoff,attempt_count__gte=4,
    ).update(status='failed',error='توقف worker پس از چند تلاش')

    processed=0
    for _ in range(batch_size):
        with transaction.atomic():
            item=(SmsScheduledMessage.objects.select_for_update(skip_locked=True)
                  .filter(status='pending',due_at__lte=timezone.now())
                  .order_by('due_at','id').first())
            if not item:
                break
            if not _current_call_outcome(item):
                item.status='cancelled'
                item.save(update_fields=['status','updated_at'])
                continue
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


NETWORK_WELCOME_EVENT='network_member_joined'


def queue_network_welcome_sms(member, *, public=False, resend=False):
    """Queue one Iranian member welcome SMS; never transmit passwords.

    Returning a status instead of sending on the request thread keeps signup
    independent of external SMS latency. A dedicated SMS worker dispatches it.
    """
    import re
    from django.urls import reverse
    from django.db.models import Q
    from .models import ApiServerSettings, SmsAutomationRule, SmsScheduledMessage

    config=ApiServerSettings.load()
    if not (config.is_enabled and config.is_configured):
        return 'gateway_unavailable'
    rule=SmsAutomationRule.objects.filter(event=NETWORK_WELCOME_EVENT,is_enabled=True).first()
    if not rule or rule.recipient!='patient':
        return 'rule_disabled'

    raw=re.sub(r'[^0-9]', '', str(member.phone or ''))
    if raw.startswith('0098'):
        raw='0'+raw[4:]
    elif raw.startswith('98') and len(raw)==12:
        raw='0'+raw[2:]
    if not (len(raw)==11 and raw.startswith('09')):
        return 'invalid_phone'

    kind='public' if public else 'referral'
    key=f'{kind}-{member.pk}'
    prefix=f'{NETWORK_WELCOME_EVENT}:{key}'
    previous=SmsScheduledMessage.objects.filter(rule=rule).filter(
        Q(event_key=prefix+':patient') | Q(event_key__startswith=prefix+'-retry-')
    )
    if resend:
        if previous.filter(status__in=('pending','sending')).exists():
            return 'already_queued'
        if previous.filter(created_at__gte=timezone.now()-timedelta(minutes=5)).exists():
            return 'recently_sent'
        key=f'{key}-retry-{timezone.now():%Y%m%d%H%M%S%f}'

    login_path=reverse('public_network:login' if public else 'login')
    base=getattr(settings,'PUBLIC_BASE_URL','https://staff.greenlifeclinics.com').rstrip('/')
    record=schedule_sms_event(
        NETWORK_WELCOME_EVENT,key,patient_number=raw,
        context={
            'name':member.user.first_name or member.user.get_full_name() or 'همکار',
            'username':member.user.username,
            'login_url':base+login_path,
        },
    )
    return 'queued' if record else 'not_queued'
