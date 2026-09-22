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

# Night/no-staff leads stay in a pending queue. On normal workdays that queue is
# released at 11:00 (or earlier only if every expected operator has checked in).
# This prevents the first person arriving at 09:00 from receiving the whole
# overnight backlog. Friday keeps the existing duty-day behaviour and releases
# as soon as the on-duty operator is present.
PENDING_MORNING_RELEASE_HOUR = 11


def _normalize(value):
    return ' '.join(
        str(value or '').strip().lower().replace('ي', 'ی').replace('ك', 'ک').split()
    )


def operator_weight(operator):
    """Current phase: all present call-center operators have equal weight.

    A KPI/performance multiplier can be added here later without changing the
    pending-queue and attendance-aware routing flow.
    """
    return 1


def expected_operator_user_ids(day=None):
    """Active call-center users expected to work today, excluding approved leave."""
    day = day or timezone.localdate()
    user_ids = set(
        EmployeeProfile.objects.filter(
            role='call_center',
            is_active=True,
            user__is_active=True,
        ).values_list('user_id', flat=True)
    )
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


def _pick_balanced_operator(operators, stats):
    def key(operator):
        row = stats.get(operator.id) or {}
        count = row.get('count') or 0
        last_at = row.get('last_at')
        return (
            count,
            last_at or timezone.datetime.min.replace(
                tzinfo=timezone.get_current_timezone()
            ),
            operator.id,
        )

    return min(operators, key=key) if operators else None


def _locked_balanced_operator(now=None):
    """Pick the present operator with the fewest assignments made today.

    Because the metric is assignment time (not lead creation time), an operator
    arriving at 10:00 or 11:00 starts behind the people already present and
    automatically receives subsequent leads until the daily counts catch up.
    """
    local_now = timezone.localtime(now or timezone.now())
    day = local_now.date()
    operators = _locked_present_operators(day)
    if not operators:
        return None
    return _pick_balanced_operator(operators, _assignment_stats(operators, day))


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


def _pending_destination(lead):
    """Recover the operational destination for an unassigned lead."""
    notes = _normalize(getattr(lead, 'notes', ''))
    source_url = _normalize(getattr(lead, 'source_url', ''))

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
    if not eligible_user_ids:
        return False
    # Friday is a duty day: do not wait for the normal team.
    if local_now.weekday() == 4:
        return True
    expected = expected_operator_user_ids(local_now.date())
    if expected and expected.issubset(eligible_user_ids):
        return True
    return local_now.hour >= PENDING_MORNING_RELEASE_HOUR


@transaction.atomic
def release_pending_leads_if_ready(*, force=False, now=None):
    """Distribute queued unassigned leads equally among operators who are present.

    Before 11:00 on normal workdays the overnight backlog is held unless all
    expected operators have already arrived. This is intentionally different
    from a brand-new daytime lead: new leads can still go immediately to whoever
    is present, and late arrivals then catch up because routing uses assigned_at.
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

    stats = _assignment_stats(operators, day)
    counts = {op.id: int((stats.get(op.id) or {}).get('count') or 0) for op in operators}
    last_order = {op.id: index for index, op in enumerate(operators)}

    assigned = 0
    for lead in pending:
        operator = min(
            operators,
            key=lambda op: (counts[op.id], last_order[op.id], op.id),
        )
        group_name, title = _pending_destination(lead)
        _assign_to_operator(
            lead,
            operator,
            group_name,
            title,
            notify=True,
            assigned_at=timezone.now(),
        )
        counts[operator.id] += 1
        # Move the selected operator to the back of equal-count ties.
        for op_id in last_order:
            last_order[op_id] -= 1
        last_order[operator.id] = len(operators)
        assigned += 1

    return assigned


def _release_before_live_assignment():
    # After the morning release point (or when the whole expected team is in),
    # clear the pending queue before routing the newest lead.
    release_pending_leads_if_ready()


@transaction.atomic
def assign_external_lead(lead, channel):
    _release_before_live_assignment()
    lead.refresh_from_db(fields=['assigned_to', 'group', 'assigned_at'])
    if lead.assigned_to_id:
        return lead.assigned_to

    operator = _locked_balanced_operator()
    if not operator:
        return None

    label = CHANNEL_LABELS.get(channel, channel)
    group_name = 'اینستاگرام جدید' if channel == 'instagram' else f'ورودی {label}'
    return _assign_to_operator(
        lead,
        operator,
        group_name,
        f'لید جدید {label}',
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
    lead.refresh_from_db(fields=['assigned_to', 'group', 'assigned_at'])
    if lead.assigned_to_id:
        return lead.assigned_to

    operator = _locked_balanced_operator()
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
    lead.refresh_from_db(fields=['assigned_to', 'group', 'assigned_at'])
    if lead.assigned_to_id:
        return lead.assigned_to

    operator = _locked_balanced_operator()
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
