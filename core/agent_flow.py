"""Read-only daily counters for the executive activity map."""
from collections import Counter

from django.db.models import Case, Count, Q, Value, When

from .customer_portal_models import CustomerPortalMember, CustomerServiceRequest
from .lead_group_names import normalized_group_name
from .me_sync_models import MeSyncAudit
from .models import ReferralLead


def daily_flow(now):
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    window = {'created_at__gte': start, 'created_at__lte': now}
    counts = Counter()
    counts['account'] = CustomerPortalMember.objects.filter(
        last_login_at__isnull=False, **window
    ).count()
    counts['sync'] = MeSyncAudit.objects.filter(action='sync', **window).count()
    requests = CustomerServiceRequest.objects.filter(**window).aggregate(
        request=Count('pk', filter=Q(kind='visit')),
        booked=Count('pk', filter=Q(kind='visit', visit_appointment__isnull=False, status='booked')),
        diet=Count('pk', filter=Q(kind='diet')),
        device=Count('pk', filter=Q(kind='device')),
        network=Count('pk', filter=Q(kind='network')),
    )
    counts.update(requests)

    rows = ReferralLead.objects.filter(**window).order_by().values(
        'group__name', 'status',
        is_school=Case(When(school_enrollment__isnull=False, then=Value(True)), default=Value(False)),
    ).annotate(total=Count('pk'), assigned=Count('assigned_to'))
    groups = {'وب سایت': 'website', 'اینستاگرام': 'instagram'}
    for row in rows:
        key = groups.get(normalized_group_name(row['group__name']), 'other')
        if row['is_school']:
            key = 'school'
        counts[key] += row['total']
        counts['lead_' + row['status']] += row['total']
        counts['crm'] += row['total']
        counts['assigned'] += row['assigned']

    return {'day': start.date().isoformat(), 'counts': dict(counts)}
