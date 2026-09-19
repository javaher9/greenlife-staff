from django.db import transaction
from django.db.models import Count, Max
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

# One routing policy for every lead source.
# Target share when all six known operators are active:
# Narges 30%, Khorshidi 20%, Banafsheh 15%, Kamelia 15%, Yasaman 15%, Laleh 5%.
OPERATOR_WEIGHT_RULES = (
    (('بابایی', 'babaei', 'babayi', 'babaee'), 6),
    (('صالحی', 'salehi'), 4),
    (('عباسی', 'abbasi'), 1),
)
DEFAULT_OPERATOR_WEIGHT = 3
FRIDAY_DUTY_MIN_WEIGHT = 8
FRIDAY_DUTY_WEIGHT_MULTIPLIER = 2
FRIDAY_DUTY_START_HOUR = 12
FRIDAY_DUTY_END_HOUR = 18


def _normalize(value):
    return ' '.join(
        str(value or '').strip().lower().replace('ي', 'ی').replace('ك', 'ک').split()
    )


def operator_weight(operator):
    user = operator.user
    identity = _normalize(' '.join(
        part for part in (user.first_name, user.last_name, user.username) if part
    ))
    for aliases, weight in OPERATOR_WEIGHT_RULES:
        if any(_normalize(alias) in identity for alias in aliases):
            return weight
    return DEFAULT_OPERATOR_WEIGHT


def eligible_operator_user_ids(day=None):
    """Users eligible to receive new leads right now.

    An operator must have an active check-in for today, must not have checked out,
    and must not be on approved leave. This keeps new leads away from absent or
    unavailable call-center staff without changing their historical ownership.
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


def friday_duty_weight(operator, now=None):
    """Boost the operator who is physically on Friday duty from 12:00 to 18:00.

    Friday is normally off for call-center staff. If an operator has actually
    checked in, they become the duty operator for routing purposes. The boost is
    intentionally layered on top of the normal per-operator weights and expires
    automatically at 18:00 (or immediately after check-out).
    """
    local_now = timezone.localtime(now or timezone.now())
    today = local_now.date()
    if today.weekday() != 4:
        return operator_weight(operator)
    if not (FRIDAY_DUTY_START_HOUR <= local_now.hour < FRIDAY_DUTY_END_HOUR):
        return operator_weight(operator)

    attendance = Attendance.objects.filter(
        user=operator.user,
        date=today,
        check_in__isnull=False,
    ).only('check_in', 'check_out').first()
    if not attendance:
        return operator_weight(operator)
    if attendance.check_out and timezone.localtime(attendance.check_out) <= local_now:
        return operator_weight(operator)

    base = operator_weight(operator)
    return max(base * FRIDAY_DUTY_WEIGHT_MULTIPLIER, FRIDAY_DUTY_MIN_WEIGHT)


def _locked_balanced_operator():
    """Return the next active operator using a weighted round-robin balance.

    All active call-center rows are locked until the caller's transaction commits,
    so simultaneous lead submissions cannot all choose the same operator.

    Selection uses today's assigned leads / operator weight. The operator with the
    lowest ratio is chosen. That makes the first pass genuinely rotational (an
    operator who just received a lead will not receive another while peers are at
    zero), while the long-run distribution converges to the requested weights.
    """
    today = timezone.localdate()
    eligible_user_ids = eligible_operator_user_ids(today)
    if not eligible_user_ids:
        return None

    operators = list(
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
    if not operators:
        return None

    ids = [operator.id for operator in operators]
    stats = {
        row['assigned_to_id']: row
        for row in (
            ReferralLead.objects
            .filter(assigned_to_id__in=ids, created_at__date=today)
            .values('assigned_to_id')
            .annotate(count=Count('id'), last_at=Max('created_at'))
        )
    }

    def key(operator):
        row = stats.get(operator.id) or {}
        count = row.get('count') or 0
        last_at = row.get('last_at')
        # The ratio provides weighted fairness. The second key prevents repeated
        # assignment on ties by preferring the operator who has waited longest.
        effective_weight = friday_duty_weight(operator)
        return (
            count / effective_weight,
            -effective_weight,
            last_at or timezone.datetime.min.replace(tzinfo=timezone.get_current_timezone()),
            operator.id,
        )

    return min(operators, key=key)


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


@transaction.atomic
def assign_external_lead(lead, channel):
    operator = _locked_balanced_operator()
    if not operator:
        return None

    label = CHANNEL_LABELS.get(channel, channel)
    group_name = 'اینستاگرام جدید' if channel == 'instagram' else f'ورودی {label}'
    lead.assigned_to = operator
    lead.group = _group_for(operator, group_name)
    lead.save(update_fields=['assigned_to', 'group', 'updated_at'])
    StaffNotification.objects.create(
        user=operator.user,
        title=f'لید جدید {label}',
        message=f'{lead.full_name} با شماره {lead.phone} وارد «{group_name}» شد.',
        notification_type='call_center_lead',
        related_date=timezone.localdate(),
    )
    return operator


@transaction.atomic
def assign_referral_lead(lead):
    if lead.assigned_to_id:
        if not lead.group_id:
            lead.group = _group_for(lead.assigned_to, 'شبکه فروش پرسنل', is_default=True)
            lead.save(update_fields=['group', 'updated_at'])
        return lead.assigned_to

    operator = _locked_balanced_operator()
    if not operator:
        return None

    lead.assigned_to = operator
    lead.group = _group_for(operator, 'شبکه فروش پرسنل', is_default=True)
    lead.save(update_fields=['assigned_to', 'group', 'updated_at'])
    StaffNotification.objects.create(
        user=operator.user,
        title='لید جدید برای تماس',
        message=f'{lead.full_name} با شماره {lead.phone} به صف پیگیری شما اضافه شد.',
        notification_type='call_center_lead',
        related_date=timezone.localdate(),
    )
    return operator


@transaction.atomic
def assign_social_lead(lead, group_name='اینستاگرام - لینک', notification_title='لید جدید اینستاگرام'):
    operator = _locked_balanced_operator()
    if not operator:
        return None

    lead.assigned_to = operator
    lead.group = _group_for(operator, group_name)
    lead.save(update_fields=['assigned_to', 'group', 'updated_at'])
    StaffNotification.objects.create(
        user=operator.user,
        title=notification_title,
        message=f'{lead.full_name} با شماره {lead.phone} به گروه «{group_name}» اضافه شد.',
        notification_type='call_center_lead',
        related_date=timezone.localdate(),
    )
    return operator


def install_unified_lead_routing():
    """Install one routing engine behind all existing lead-entry paths."""
    from . import instagram_views, lead_ingest_views, referral_views

    lead_ingest_views._assign_lead = assign_external_lead
    referral_views._auto_assign_call_center = assign_referral_lead
    instagram_views._assign_instagram_lead = assign_social_lead
