from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from .models import Attendance, CallCenterLeadGroup, EmployeeProfile, LeaveRequest, ReferralLead, StaffNotification


CHANNEL_LABELS = {
    'website': 'وب‌سایت',
    'instagram': 'اینستاگرام',
    'crm': 'CRM',
    'whatsapp': 'واتس‌اپ',
    'campaign': 'کمپین',
    'partner': 'همکار',
}

OPEN_ROUTING_STATUSES = ('new', 'contacted', 'appointment')

# Overnight/no-staff leads stay in a pending queue. On normal workdays the
# backlog is released progressively so the first person arriving in the morning
# cannot receive the whole queue. At 11:15 the remaining backlog is released in
# full among whoever is present. Friday is a duty day: as soon as the first
# eligible operator checks in, the whole pending queue may be released to them.
PENDING_MORNING_RELEASE_HOUR = 11
PENDING_MORNING_RELEASE_MINUTE = 15

# Fixed equal-weight rotation requested by management. The order itself is the
# policy: Narges -> Banafsha -> Yasaman -> Khorshidi -> repeat. Absent operators
# are skipped; when they later check in they join the same rotation without any
# catch-up burst.
ROTATION_OPERATOR_IDENTITIES = (
    ('فاطمه بابایی', 'بابایی', 'fatemeh babaei', 'babaei', 'babayi', 'نرگس', 'narges'),
    ('حدیث توانا', 'توانا', 'hadis tavana', 'tavana', 'بنفشه', 'banafsha', 'banafsheh'),
    ('زهرا آزادی', 'آزادی', 'zahra azadi', 'azadi', 'یاسمن', 'yasaman'),
    ('محمد صالحی', 'صالحی', 'mohammad salehi', 'salehi', 'خورشیدی', 'khorshidi'),
)

# Management routing policy (2026-10-03): Kamelya and Laleh must not receive
# any new lead until further notice. Existing ownership is deliberately kept.
# Match both real staff identities and the flower aliases used in call-center
# screens.
BLOCKED_OPERATOR_IDENTITIES = (
    'پریسا کلکلی', 'کلکلی', 'kolkoli', 'kalakali', 'کاملیا',
    'شیما عباسی', 'عباسی', 'abbasi', 'لاله',
)

# All four rotation operators now have exactly the same routing weight.
REDUCED_OPERATOR_WEIGHT_RULES = ()
KHORSHIDI_POLICY_NOTICE = ''


TURKEY_OPERATOR_IDENTITIES = (
    'فاطمه بابایی', 'بابایی', 'fatemeh babaei', 'babaei', 'babayi', 'نرگس', 'narges',
)


def _is_turkey_lead(lead):
    country=getattr(lead,'country',None)
    return bool(country and getattr(country,'code','') == 'TR')


def _turkey_operator(*, lock=False):
    qs=EmployeeProfile.objects.filter(
        role='call_center',
        is_active=True,
        user__is_active=True,
    ).select_related('user')
    if lock:
        qs=qs.select_for_update()
    for operator in qs.order_by('id'):
        if _identity_matches(operator,TURKEY_OPERATOR_IDENTITIES):
            return operator
    return None


def _assign_turkey_lead(lead, *, notify=True):
    operator=_turkey_operator(lock=True)
    if not operator:
        return None
    return _assign_to_operator(
        lead,
        operator,
        'Türkiye | Turkey',
        'لید جدید ترکیه',
        notify=notify,
    )

# Recent performance metrics still fine-tune unrestricted operators. Manual
# management blocks and reductions above take precedence over this calculation.
CONTACT_RATE_WINDOW_DAYS = 7
CONTACT_RATE_MIN_AGE_HOURS = 2
CONTACT_OUTCOME_VALUES = ('follow_up', 'appointment', 'no_answer', 'won', 'sale_lost', 'not_interested')
ENGAGED_OUTCOME_VALUES = ('follow_up', 'appointment', 'won')
ATTENDANCE_WINDOW_DAYS = 14


def _normalize(value):
    return ' '.join(
        str(value or '').strip().lower().replace('ي', 'ی').replace('ك', 'ک').split()
    )


def _operator_identity(operator):
    user=getattr(operator,'user',None)
    return _normalize(' '.join(
        part for part in (
            getattr(user,'first_name',''),
            getattr(user,'last_name',''),
            getattr(user,'username',''),
        ) if part
    ))


def _identity_matches(operator, aliases):
    identity=_operator_identity(operator)
    return any(_normalize(name) in identity for name in aliases)


def _operator_is_blocked(operator):
    return _identity_matches(operator, BLOCKED_OPERATOR_IDENTITIES)


def _rotation_rank(operator):
    for index, aliases in enumerate(ROTATION_OPERATOR_IDENTITIES):
        if _identity_matches(operator, aliases):
            return index
    return None


def _operators_for_channel(operators, channel):
    # The block is channel-agnostic: website, Instagram, WhatsApp, campaigns,
    # referral network and pending-queue releases all use the same fixed pool.
    ranked=[]
    for operator in operators:
        if _operator_is_blocked(operator):
            continue
        rank=_rotation_rank(operator)
        if rank is None:
            continue
        ranked.append((rank,operator.id,operator))
    ranked.sort(key=lambda row:(row[0],row[1]))
    return [operator for _rank,_id,operator in ranked]


def _recent_operator_metrics(operator, now=None):
    """Measured activity, engagement and punctuality, not inferred phone clicks.

    A recorded 'no_answer' counts as a call attempt but not as engagement.
    Pending/new leads are excluded until they have had two hours to be called.
    Only recorded attendance days are used; approved leave is not penalized.
    """
    now=now or timezone.now()
    cutoff=now-timedelta(days=CONTACT_RATE_WINDOW_DAYS)
    mature_before=now-timedelta(hours=CONTACT_RATE_MIN_AGE_HOURS)
    recent=ReferralLead.objects.filter(assigned_to=operator).filter(
        Q(assigned_at__gte=cutoff,assigned_at__lte=mature_before)
        | Q(assigned_at__isnull=True,created_at__gte=cutoff,created_at__lte=mature_before)
    )
    assigned=recent.count()
    # Real outcomes distinguish a logged call from a lead merely moved to
    # 'contacted'. Legacy appointments/sales still count as a completed action.
    calls=recent.filter(
        Q(contact_result__in=CONTACT_OUTCOME_VALUES)
        | Q(status__in=('appointment','visited','won'))
    ).count()
    engaged=recent.filter(
        Q(contact_result__in=ENGAGED_OUTCOME_VALUES)
        | Q(status__in=('appointment','visited','won'))
    ).count()

    attendance=Attendance.objects.filter(
        user=operator.user,
        date__gte=timezone.localtime(now).date()-timedelta(days=ATTENDANCE_WINDOW_DAYS),
        date__lte=timezone.localtime(now).date(),
    ).exclude(status='leave')
    attendance_total=attendance.count()
    punctual=attendance.filter(status='present',check_in__isnull=False).count()
    # Neutral prior for low volume; the number of calls contributes separately.
    contact_rate=(calls+3.5)/(assigned+5)
    engagement_rate=(engaged+2)/(calls+5) if calls else 0.4
    volume=min(calls/20,1) if assigned else 0.5
    punctuality=(punctual+2)/(attendance_total+2.5) if attendance_total else 0.8
    return contact_rate,engagement_rate,volume,punctuality


def operator_weight(operator, now=None):
    """All four active rotation operators have identical lead weight."""
    return 1.0


def operator_policy_notice(operator):
    """No operator is currently under a reduced-weight warning."""
    return ''


def expected_operator_user_ids(day=None):
    """Active call-center users expected to work today, excluding approved leave."""
    day = day or timezone.localdate()
    active=list(
        EmployeeProfile.objects.filter(
            role='call_center',
            is_active=True,
            user__is_active=True,
        ).select_related('user')
    )
    user_ids={operator.user_id for operator in _operators_for_channel(active,None)}
    if not user_ids:
        return set()
    leave_ids = set(
        LeaveRequest.objects.filter(
            user_id__in=user_ids,
            status='approved',
            start_date__lte=day,
            end_date__gte=day,
        ).values_list('user_id', flat=True)
    )
    return user_ids - leave_ids


def eligible_operator_user_ids(day=None):
    """Users eligible to receive new leads right now.

    An operator must have checked in today, must not have checked out, and must
    not be on approved leave. Historical ownership is never changed by absence.
    """
    day = day or timezone.localdate()
    present_ids = set(
        Attendance.objects.filter(
            date=day,
            check_in__isnull=False,
            check_out__isnull=True,
            user__profile__role='call_center',
            user__profile__is_active=True,
            user__is_active=True,
        ).values_list('user_id', flat=True)
    )
    if not present_ids:
        return set()
    leave_ids = set(
        LeaveRequest.objects.filter(
            user_id__in=present_ids,
            status='approved',
            start_date__lte=day,
            end_date__gte=day,
        ).values_list('user_id', flat=True)
    )
    return present_ids - leave_ids


def _locked_present_operators(day=None):
    day = day or timezone.localdate()
    eligible_user_ids = eligible_operator_user_ids(day)
    if not eligible_user_ids:
        return []
    return list(
        EmployeeProfile.objects
        .select_for_update()
        .filter(
            role='call_center',
            is_active=True,
            user__is_active=True,
            user_id__in=eligible_user_ids,
        )
        .select_related('user')
        .order_by('id')
    )


def _assignment_stats(operators, day):
    ids = [operator.id for operator in operators]
    return {
        row['assigned_to_id']: row
        for row in (
            ReferralLead.objects
            .filter(assigned_to_id__in=ids)
            .filter(
                Q(assigned_at__date=day)
                | Q(assigned_at__isnull=True, created_at__date=day)
            )
            .values('assigned_to_id')
            .annotate(count=Count('id'), last_at=Max('assigned_at'))
        )
    }


def _last_assigned_operator_id(operators, day):
    """Return the most recently assigned eligible operator for today's rotation."""
    ids=[operator.id for operator in operators]
    if not ids:
        return None
    row=(
        ReferralLead.objects
        .filter(assigned_to_id__in=ids)
        .filter(
            Q(assigned_at__date=day)
            | Q(assigned_at__isnull=True, created_at__date=day)
        )
        .order_by('-assigned_at','-created_at','-id')
        .values('assigned_to_id')
        .first()
    )
    return row['assigned_to_id'] if row else None


def _rotation_order(operators, day):
    """Round-robin order beginning immediately after the last recipient.

    This deliberately avoids catch-up bursts. With multiple eligible operators,
    the same operator will not receive two consecutive new leads until the
    rotation has passed through the others.
    """
    operators=list(operators)
    if not operators:
        return []
    last_id=_last_assigned_operator_id(operators, day)
    if last_id is None:
        return operators
    last_index=next((i for i,op in enumerate(operators) if op.id==last_id),-1)
    start=(last_index+1)%len(operators)
    return operators[start:]+operators[:start]


def _reduced_operator_can_receive(operator, operators, stats):
    """Apply explicit management reductions without creating catch-up bursts.

    Reduced operators receive roughly their configured fraction of a regular
    operator's share. If they are the only eligible staff member, routing still
    continues so leads are not lost.
    """
    rule_weight=None
    for aliases, weight in REDUCED_OPERATOR_WEIGHT_RULES:
        if _identity_matches(operator, aliases):
            rule_weight=weight
            break
    if rule_weight is None:
        return True

    regular=[
        op for op in operators
        if not any(_identity_matches(op, aliases) for aliases,_weight in REDUCED_OPERATOR_WEIGHT_RULES)
    ]
    if not regular:
        return True

    min_regular=min(stats.get(op.id,{}).get('count',0) for op in regular)
    allowed_count=int(min_regular * rule_weight)
    current=stats.get(operator.id,{}).get('count',0)
    return current < allowed_count


def _next_no_burst_operator(operators, day):
    """Pick the next operator in rotation, never by daily catch-up deficit."""
    operators=list(operators)
    if not operators:
        return None
    stats=_assignment_stats(operators,day)
    for operator in _rotation_order(operators,day):
        if _reduced_operator_can_receive(operator,operators,stats):
            return operator
    # If the only remaining candidates are reduced, do not strand the lead.
    return _rotation_order(operators,day)[0]


def _locked_round_robin_operator(now=None, channel=None):
    local_now=timezone.localtime(now or timezone.now())
    day=local_now.date()
    operators=_operators_for_channel(_locked_present_operators(day),channel)
    if not operators:
        return None
    return _next_no_burst_operator(operators,day)


def _group_for(operator, name, *, is_default=False):
    group, _ = CallCenterLeadGroup.objects.get_or_create(
        owner=operator,
        name=name,
        defaults={'is_default': is_default},
    )
    if is_default and not group.is_default:
        group.is_default = True
        group.save(update_fields=['is_default'])
    return group


def _is_beytoote_reportage_start(lead):
    source_url=_normalize(getattr(lead,'source_url',''))
    notes=_normalize(getattr(lead,'notes',''))
    is_beytoote=(
        'utm_source=beytoote' in source_url
        or '"utm_source":"beytoote"' in notes
    )
    is_reportage=(
        'utm_medium=reportage' in source_url
        or '"utm_medium":"reportage"' in notes
    )
    return is_beytoote and is_reportage


def _pending_channel(lead):
    """Recover the routing channel for an unassigned lead."""
    notes=_normalize(getattr(lead,'notes',''))
    source_url=_normalize(getattr(lead,'source_url',''))
    if '[channel:website]' in notes or 'greenlifeclinics.com' in source_url:
        return 'website'
    if '[channel:instagram]' in notes or '[instagram_page:' in notes or '/instagram/' in source_url:
        return 'instagram'
    if '[channel:crm]' in notes or 'crm' in source_url:
        return 'crm'
    if '[channel:whatsapp]' in notes or 'whatsapp' in source_url or 'wa.me' in source_url:
        return 'whatsapp'
    if '[channel:campaign]' in notes or 'utm_campaign=' in source_url:
        return 'campaign'
    return None


def _pending_destination(lead):
    """Recover the operational destination for an unassigned lead."""
    notes = _normalize(getattr(lead, 'notes', ''))
    source_url = _normalize(getattr(lead, 'source_url', ''))

    if _is_beytoote_reportage_start(lead):
        return 'رپورتاژ - استارت', 'لید جدید بیتوته - رپورتاژ'
    if 'اینستاگرام - دستی' in notes:
        return 'اینستاگرام - دستی', 'لید جدید اینستاگرام - دستی'
    if 'تلگرام' in notes or '/telegram/' in source_url:
        return 'تلگرام - لینک', 'لید جدید تلگرام'
    if 'بله' in notes or '[channel:bale]' in notes or '/bale/' in source_url:
        return 'بله - لینک', 'لید جدید بله'
    if '[channel:instagram]' in notes or '[instagram_page:' in notes or '/instagram/' in source_url:
        return 'اینستاگرام جدید', 'لید جدید اینستاگرام'
    if '[channel:website]' in notes or 'greenlifeclinics.com' in source_url:
        return 'ورودی وب‌سایت', 'لید جدید وب‌سایت'
    if '[channel:crm]' in notes or 'crm' in source_url:
        return 'ورودی CRM', 'لید جدید CRM'
    if '[channel:whatsapp]' in notes or 'whatsapp' in source_url or 'wa.me' in source_url:
        return 'ورودی واتس‌اپ', 'لید جدید واتس‌اپ'
    if '[channel:campaign]' in notes or 'utm_campaign=' in source_url:
        return 'ورودی کمپین', 'لید جدید کمپین'
    return 'شبکه فروش پرسنل', 'لید جدید برای تماس'


def _assign_to_operator(lead, operator, group_name, notification_title, *, notify=True, assigned_at=None):
    lead.assigned_to = operator
    lead.group = _group_for(
        operator,
        group_name,
        is_default=(group_name == 'شبکه فروش پرسنل'),
    )
    lead.assigned_at = assigned_at or timezone.now()
    lead.save(update_fields=['assigned_to', 'group', 'assigned_at', 'updated_at'])
    if notify:
        StaffNotification.objects.create(
            user=operator.user,
            title=notification_title,
            message=f'{lead.full_name} با شماره {lead.phone} به گروه «{group_name}» اضافه شد.',
            notification_type='call_center_lead',
            related_date=timezone.localdate(),
        )
    return operator


def _pending_release_ready(local_now, eligible_user_ids):
    # Any present eligible operator can start receiving part of the morning
    # backlog. Friday is intentionally immediate/full; normal days are capped
    # progressively until the 11:15 hard release point.
    return bool(eligible_user_ids)


def _morning_release_fraction(local_now):
    """Cumulative share of the overnight backlog allowed out before 11:15."""
    if local_now.weekday() == 4:
        return 1.0
    current=local_now.time()
    if current >= time(PENDING_MORNING_RELEASE_HOUR, PENDING_MORNING_RELEASE_MINUTE):
        return 1.0
    if current >= time(11, 0):
        return 0.75
    if current >= time(10, 0):
        return 0.50
    return 0.25


def _pending_release_quota(local_now, pending):
    """How many queued leads may be released in this pass.

    The calculation is cumulative for leads that were already waiting before
    the current local day. This keeps repeated live arrivals from draining the
    entire overnight queue early.
    """
    if not pending:
        return 0
    if local_now.weekday() == 4:
        return len(pending)
    if local_now.time() >= time(PENDING_MORNING_RELEASE_HOUR, PENDING_MORNING_RELEASE_MINUTE):
        return len(pending)

    tz=timezone.get_current_timezone()
    day_start=timezone.make_aware(datetime.combine(local_now.date(), time.min), tz)
    overnight_pending=[lead for lead in pending if lead.created_at < day_start]
    if not overnight_pending:
        # Daytime leads that arrived while nobody was present may be released
        # normally once staff are available.
        return len(pending)

    already_released=ReferralLead.objects.filter(
        created_at__lt=day_start,
        assigned_at__date=local_now.date(),
        status__in=OPEN_ROUTING_STATUSES,
    ).count()
    total_backlog=already_released+len(overnight_pending)
    target=int((total_backlog*_morning_release_fraction(local_now))+0.999999)
    overnight_quota=max(0,target-already_released)

    # Do not hold today's newly queued leads behind the overnight quota.
    daytime_count=len(pending)-len(overnight_pending)
    return min(len(pending),overnight_quota+daytime_count)

@transaction.atomic
def release_pending_leads_if_ready(*, force=False, now=None):
    """Distribute queued leads using the fixed equal-weight rotation.

    Normal days release the overnight queue progressively (25% before 10:00,
    50% by 10:00, 75% by 11:00) and release everything still waiting at 11:15.
    Friday releases the full queue as soon as the first eligible operator is in.
    """
    local_now = timezone.localtime(now or timezone.now())
    day = local_now.date()
    eligible_ids = eligible_operator_user_ids(day)
    if not force and not _pending_release_ready(local_now, eligible_ids):
        return 0

    operators = _locked_present_operators(day)
    if not operators:
        return 0

    pending = list(
        ReferralLead.objects
        .select_for_update()
        .select_related('referrer')
        .filter(
            assigned_to__isnull=True,
            status__in=OPEN_ROUTING_STATUSES,
        )
        .order_by('created_at', 'id')
    )
    if not pending:
        return 0

    operators=_operators_for_channel(operators,None)
    website_operators=_operators_for_channel(operators,'website')
    if not operators:
        return 0

    release_quota=_pending_release_quota(local_now,pending)
    if release_quota <= 0:
        return 0

    assigned = 0
    for lead in pending:
        if assigned >= release_quota:
            break
        if _is_turkey_lead(lead):
            operator=_turkey_operator(lock=True)
            if not operator:
                continue
            _assign_to_operator(
                lead,operator,'Türkiye | Turkey','لید جدید ترکیه',
                notify=True,assigned_at=timezone.now(),
            )
            assigned += 1
            continue
        channel=_pending_channel(lead)
        pool=website_operators if channel=='website' else operators
        if not pool:
            # Never fall back to disallowed operators for a restricted channel.
            continue
        operator=_next_no_burst_operator(pool,day)
        if not operator:
            continue
        group_name, title = _pending_destination(lead)
        _assign_to_operator(
            lead,
            operator,
            group_name,
            title,
            notify=True,
            assigned_at=timezone.now(),
        )
        assigned += 1

    return assigned


def _release_before_live_assignment():
    # After the morning release point (or when the whole expected team is in),
    # clear the pending queue before routing the newest lead.
    release_pending_leads_if_ready()


@transaction.atomic
def assign_external_lead(lead, channel):
    _release_before_live_assignment()
    lead.refresh_from_db(fields=['assigned_to', 'group', 'assigned_at', 'country'])
    if lead.assigned_to_id:
        return lead.assigned_to
    if _is_turkey_lead(lead):
        return _assign_turkey_lead(lead)

    operator = _locked_round_robin_operator(channel=channel)
    if not operator:
        return None

    label = CHANNEL_LABELS.get(channel, channel)
    if _is_beytoote_reportage_start(lead):
        group_name='رپورتاژ - استارت'
        notification_title='لید جدید بیتوته - رپورتاژ'
    else:
        group_name = 'اینستاگرام جدید' if channel == 'instagram' else f'ورودی {label}'
        notification_title=f'لید جدید {label}'
    return _assign_to_operator(
        lead,
        operator,
        group_name,
        notification_title,
    )


@transaction.atomic
def assign_referral_lead(lead):
    if lead.assigned_to_id:
        if not lead.group_id:
            lead.group = _group_for(lead.assigned_to, 'شبکه فروش پرسنل', is_default=True)
            lead.save(update_fields=['group', 'updated_at'])
        if not lead.assigned_at:
            lead.assigned_at = timezone.now()
            lead.save(update_fields=['assigned_at', 'updated_at'])
        return lead.assigned_to

    _release_before_live_assignment()
    lead.refresh_from_db(fields=['assigned_to', 'group', 'assigned_at', 'country'])
    if lead.assigned_to_id:
        return lead.assigned_to
    if _is_turkey_lead(lead):
        return _assign_turkey_lead(lead)

    operator = _locked_round_robin_operator()
    if not operator:
        return None

    return _assign_to_operator(
        lead,
        operator,
        'شبکه فروش پرسنل',
        'لید جدید برای تماس',
    )


@transaction.atomic
def assign_social_lead(lead, group_name='اینستاگرام - لینک', notification_title='لید جدید اینستاگرام'):
    _release_before_live_assignment()
    lead.refresh_from_db(fields=['assigned_to', 'group', 'assigned_at', 'country'])
    if lead.assigned_to_id:
        return lead.assigned_to
    if _is_turkey_lead(lead):
        return _assign_turkey_lead(lead)

    operator = _locked_round_robin_operator()
    if not operator:
        return None

    return _assign_to_operator(
        lead,
        operator,
        group_name,
        notification_title,
    )


def install_unified_lead_routing():
    """Install one routing engine behind all existing lead-entry paths."""
    from . import instagram_views, lead_ingest_views, referral_views

    lead_ingest_views._assign_lead = assign_external_lead
    referral_views._auto_assign_call_center = assign_referral_lead
    instagram_views._assign_instagram_lead = assign_social_lead
