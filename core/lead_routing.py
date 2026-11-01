from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Count, Max, Q
from django.utils import timezone

from .models import Attendance, CallCenterLeadGroup, EmployeeProfile, LeaveRequest, ReferralLead, StaffNotification
from .lead_routing_models import CallCenterRoutingDay


CHANNEL_LABELS = {
    'website': 'وب‌سایت',
    'instagram': 'اینستاگرام',
    'crm': 'CRM',
    'whatsapp': 'واتس‌اپ',
    'campaign': 'کمپین',
    'partner': 'همکار',
}

OPEN_ROUTING_STATUSES = ('new', 'contacted', 'appointment')

# Before 10:15 each present flower receives one fifth of the SAME opening
# queue, once. At 10:15 the remainder balances the four active flowers,
# including those not checked in (approved leave is still excluded).
# Friday retains the on-duty-only exception. Assigned leads never move.
PENDING_MORNING_RELEASE_HOUR = 10
PENDING_MORNING_RELEASE_MINUTE = 15
# No overnight automatic distribution on any day, even for remotely checked-in staff.
# Queue leads from 20:00 until 08:00 for normal morning allocation.
DAILY_LEAD_ROUTING_END = time(20, 0)
# Attendance is not permission to receive overnight leads.
DAILY_LEAD_ROUTING_START = time(8, 0)

# Equal-weight rotation requested by management. Laleh is reinstated as
# the fifth eligible operator, subject to normal attendance/leave checks. Absent operators
# are skipped; when they later check in they join the same rotation without any
# catch-up burst.
ROTATION_OPERATOR_IDENTITIES = (
    ('فاطمه بابایی', 'بابایی', 'fatemeh babaei', 'babaei', 'babayi', 'نرگس', 'narges'),
    ('حدیث توانا', 'توانا', 'hadis tavana', 'tavana', 'بنفشه', 'banafsha', 'banafsheh'),
    ('زهرا آزادی', 'آزادی', 'zahra azadi', 'azadi', 'یاسمن', 'yasaman'),
    ('محمد صالحی', 'صالحی', 'mohammad salehi', 'salehi', 'خورشیدی', 'khorshidi'),
    ('شیما عباسی', 'عباسی', 'shima abbasi', 'abbasi', 'لاله', 'laleh'),
)

# Management routing policy: Kamelya remains blocked; Laleh was reinstated
# on 2026-10-22. Existing ownership is deliberately kept.
# Match both real staff identities and the flower aliases used in call-center
# screens.
BLOCKED_OPERATOR_IDENTITIES = (
    'پریسا کلکلی', 'کلکلی', 'kolkoli', 'kalakali', 'کاملیا',
)

# All eligible rotation operators have exactly the same routing weight.
REDUCED_OPERATOR_WEIGHT_RULES = ((('شیما عباسی', 'عباسی', 'shima abbasi', 'abbasi', 'لاله', 'laleh'), 0.5),)
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


def _morning_quota(operator, opening_total):
    """Laleh receives 10% of the overnight opening queue; others 20%."""
    base = opening_total // 5
    if _identity_matches(operator, REDUCED_OPERATOR_WEIGHT_RULES[0][0]):
        return opening_total // 10
    return base


def _settlement_target(operator, total, expected):
    """Weighted total target for the 10:15 morning settlement."""
    weights = [0.5 if _identity_matches(op, REDUCED_OPERATOR_WEIGHT_RULES[0][0]) else 1.0 for op in expected]
    own = 0.5 if _identity_matches(operator, REDUCED_OPERATOR_WEIGHT_RULES[0][0]) else 1.0
    return total * own / sum(weights)


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


def eligible_operator_user_ids(day=None, *, now=None):
    """Users eligible to receive new leads right now.

    An operator must have checked in today, must not have checked out, and must
    not be on approved leave. Historical ownership is never changed by absence.
    """
    day = day or timezone.localdate()
    present_ids = set(
        Attendance.objects.filter(
            date=day,
            check_in__isnull=False,
            check_in__lte=now or timezone.now(),
            check_out__isnull=True,
            break_started_at__isnull=True,
            user__profile__role='call_center',
            user__profile__is_active=True,
            user__is_active=True,
        ).values_list('user_id', flat=True)
    )
    if not present_ids:
        return set()
    return present_ids & expected_operator_user_ids(day)


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
    # A lone remotely present reduced-weight operator must not absorb all
    # live leads. Keep them unassigned until the rest of the call center joins.
    if len(operators) == 1 and _identity_matches(operators[0], REDUCED_OPERATOR_WEIGHT_RULES[0][0]):
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
    # Groups are shared across the whole call center.
    group, _ = CallCenterLeadGroup.objects.get_or_create(
        name=name,
        defaults={'owner':None,'is_default':is_default},
    )
    changed=[]
    if group.owner_id is not None:
        group.owner=None
        changed.append('owner')
    if is_default and not group.is_default:
        group.is_default=True
        changed.append('is_default')
    if changed:
        group.save(update_fields=changed)
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


def _release_time(local_now):
    return timezone.make_aware(
        datetime.combine(local_now.date(), time(
            PENDING_MORNING_RELEASE_HOUR, PENDING_MORNING_RELEASE_MINUTE,
        )),
        timezone.get_current_timezone(),
    )


@transaction.atomic
def release_pending_leads_if_ready(*, force=False, now=None):
    """One opening share per flower, one balancing settlement, then rotation.

    A unique day row is locked BEFORE operator/lead rows, so attendance hooks,
    the server worker and concurrent ingestion requests share the same ledger.
    `force` intentionally cannot bypass the time, attendance or exclusion rules.
    """
    local_now = timezone.localtime(now or timezone.now())
    day = local_now.date()
    release_at = _release_time(local_now)
    friday = local_now.weekday() == 4
    if local_now.time() < DAILY_LEAD_ROUTING_START:
        return 0
    if local_now.time() >= DAILY_LEAD_ROUTING_END:
        return 0
    eligible_ids = eligible_operator_user_ids(day, now=local_now)
    expected_ids = expected_operator_user_ids(day)
    if not expected_ids or ((friday or local_now < release_at) and not eligible_ids):
        return 0

    state, created = CallCenterRoutingDay.objects.get_or_create(
        date=day, defaults={'opening_at': local_now},
    )
    state = CallCenterRoutingDay.objects.select_for_update().get(pk=state.pk)
    all_operators = list(
        EmployeeProfile.objects.select_for_update()
        .filter(role='call_center', is_active=True, user__is_active=True)
        .select_related('user').order_by('id')
    )
    # Re-read attendance/leave after acquiring the routing lock.
    eligible_ids = eligible_operator_user_ids(day, now=local_now)
    expected_ids = expected_operator_user_ids(day)
    operators = _operators_for_channel(all_operators, None)
    present = [op for op in operators if op.user_id in eligible_ids]
    expected = [op for op in operators if op.user_id in expected_ids]
    pending = list(
        ReferralLead.objects.select_for_update(of=('self',))
        .select_related('referrer', 'country')
        .filter(assigned_to__isnull=True, status__in=OPEN_ROUTING_STATUSES,
                created_at__lte=local_now)
        .order_by('created_at', 'id')
    )
    domestic = [lead for lead in pending if not _is_turkey_lead(lead)]
    if created:
        # Snapshot at the first eligible check-in, including that morning's
        # accumulated leads. If first run is late, never count post-cutoff leads.
        state.opening_lead_ids = [
            lead.pk for lead in domestic if lead.created_at <= release_at
        ]
    assigned = 0
    counts = dict(state.allocation_counts)

    def assign(lead, operator, *, morning=False):
        nonlocal assigned
        group_name, title = _pending_destination(lead)
        if _is_turkey_lead(lead):
            group_name, title = 'Türkiye | Turkey', 'لید جدید ترکیه'
        _assign_to_operator(lead, operator, group_name, title,
                            notify=True, assigned_at=local_now)
        assigned += 1
        if morning:
            key = str(operator.pk)
            counts[key] = counts.get(key, 0) + 1

    if not friday and local_now < release_at:
        opening_ids = set(state.opening_lead_ids)
        queue = [lead for lead in domestic if lead.pk in opening_ids]
        arrivals = dict(Attendance.objects.filter(
            date=day, user_id__in=eligible_ids,
        ).values_list('user_id', 'check_in'))
        for operator in sorted(present, key=lambda op: (arrivals[op.user_id], op.pk)):
            if operator.pk in state.early_operator_ids:
                continue
            quota = _morning_quota(operator, len(state.opening_lead_ids))
            for lead in queue[:quota]:
                assign(lead, operator, morning=True)
            queue = queue[quota:]
            state.early_operator_ids.append(operator.pk)
    else:
        if not friday and state.settled_at is None and expected:
            # Management explicitly includes late/not-yet-present flowers in
            # this ONE settlement. No already-assigned lead is queried/moved.
            for lead in domestic:
                if lead.created_at > release_at:
                    continue
                operator = min(expected, key=lambda op: (counts.get(str(op.pk), 0) / (0.5 if _identity_matches(op, REDUCED_OPERATOR_WEIGHT_RULES[0][0]) else 1.0), op.pk))
                assign(lead, operator, morning=True)
            state.settled_at = local_now
        # Friday's entire queue, and post-cutoff leads on other days, follow
        # attendance-based round robin without a later catch-up redistribution.
        for lead in pending:
            if lead.assigned_to_id or not present:
                continue
            if _is_turkey_lead(lead):
                operator = next((op for op in all_operators
                                 if _identity_matches(op, TURKEY_OPERATOR_IDENTITIES)), None)
            else:
                operator = _next_no_burst_operator(present, day)
            if operator:
                assign(lead, operator)

    state.allocation_counts = counts
    state.save(update_fields=[
        'opening_lead_ids', 'early_operator_ids', 'allocation_counts', 'settled_at',
    ])
    return assigned


def operator_routing_summary(operator, now=None):
    """Read-only status for the operational page; no attendance is invented."""
    local_now = timezone.localtime(now or timezone.now())
    if _operator_is_blocked(operator) or _rotation_rank(operator) is None:
        return 'دریافت خودکار لید برای شما فعلاً غیرفعال است.'
    if operator.user_id not in expected_operator_user_ids(local_now.date()):
        return 'امروز به‌علت مرخصی یا غیرفعال بودن، در توزیع لید نیستید.'
    if local_now.weekday() == 4:
        return 'جمعه: صف لید بین همکاران حاضر توزیع می‌شود.'
    state = CallCenterRoutingDay.objects.filter(date=local_now.date()).first()
    if state and state.settled_at:
        received = state.allocation_counts.get(str(operator.pk), 0)
        return f'تسویه صبح انجام شد: {received} لید برای شما؛ لیدهای جدید نوبتی توزیع می‌شوند.'
    if local_now >= _release_time(local_now):
        return 'تقسیم نهایی لیدهای صبح هنوز انجام نشده است؛ زمان مقرر 10:15.'
    if not state:
        share = '10%' if _identity_matches(operator, REDUCED_OPERATOR_WEIGHT_RULES[0][0]) else '20%'
        return f'سهم صبح: {share} از صف ابتدای کار پس از ثبت ورود؛ تسویه نهایی ساعت 10:15.'
    quota = _morning_quota(operator, len(state.opening_lead_ids))
    received = state.allocation_counts.get(str(operator.pk), 0)
    return f'سهم صبح شما: {quota} لید؛ دریافت‌شده: {received}؛ تسویه نهایی ساعت 10:15.'


def _live_assignment_allowed(now=None):
    """Whether a newly arriving lead may be assigned immediately.

    Friday keeps the duty-day exception. On every other day, no automatic
    live assignment happens before 10:15; the opening-share allocator above
    is the only path that may release a morning lead.
    """
    local_now=timezone.localtime(now or timezone.now())
    if not (DAILY_LEAD_ROUTING_START <= local_now.time() < DAILY_LEAD_ROUTING_END):
        return False
    if local_now.weekday()==4:
        return True
    release_at=time(PENDING_MORNING_RELEASE_HOUR,PENDING_MORNING_RELEASE_MINUTE)
    return local_now.time() >= release_at


def _release_before_live_assignment():
    # At/after the release point (or Friday), clear eligible pending work before
    # routing the newest lead. Before 10:15 only unclaimed opening shares move.
    release_pending_leads_if_ready()


@transaction.atomic
def assign_external_lead(lead, channel):
    _release_before_live_assignment()
    lead.refresh_from_db(fields=['assigned_to', 'group', 'assigned_at', 'country'])
    if lead.assigned_to_id:
        return lead.assigned_to
    if not _live_assignment_allowed():
        return None
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
    if not _live_assignment_allowed():
        return None
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
    if not _live_assignment_allowed():
        return None
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
