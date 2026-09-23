from datetime import timedelta
from decimal import Decimal

from django import template
from django.db.models import Count, Sum
from django.utils import timezone

from core.models import (
    FinancialTransaction,
    MeetingMinute,
    ReferralLead,
    ReferralSale,
    Task,
    VisitAppointment,
)

register = template.Library()
MILLION_TOMAN = Decimal('10000000')
COLORS = ('#2ee6a6', '#33b8ff', '#a978ff', '#ffbd4a', '#ff6d9a', '#35e0dc')


def _money_million_toman(queryset):
    value = queryset.aggregate(v=Sum('amount'))['v'] or 0
    return Decimal(value) / MILLION_TOMAN


def _bar_rows(values):
    peak = max(values or [0]) or 1
    return [
        {'value': value, 'height': max(8, round(float(value) * 100 / float(peak)))}
        for value in values
    ]


@register.simple_tag
def management_dashboard_metrics(selected_branch=None):
    """Compact real-data metrics for the manager /live/ command center.

    It deliberately mirrors the branch selector used by branch_live, so the
    executive cards never show a different scope from the rest of the page.
    """
    today = timezone.localdate()
    month_start = today.replace(day=1)
    year_start = today.replace(month=1, day=1)
    yesterday = today - timedelta(days=1)

    finance = FinancialTransaction.objects.filter(
        entry_type='inc', review_status='approved'
    )
    leads = ReferralLead.objects.all()
    appointments = VisitAppointment.objects.all()
    sales = ReferralSale.objects.filter(status__in=('approved', 'paid'))
    open_tasks = Task.objects.exclude(status='done')

    if selected_branch:
        finance = finance.filter(branch=selected_branch)
        leads = leads.filter(assigned_to__branch=selected_branch)
        appointments = appointments.filter(branch=selected_branch)
        sales = sales.filter(lead__assigned_to__branch=selected_branch)
        open_tasks = open_tasks.filter(assigned_to__profile__branch=selected_branch)

    finance_today = finance.filter(occurred_at__date=today)
    finance_yesterday = finance.filter(occurred_at__date=yesterday)
    finance_month = finance.filter(occurred_at__date__range=(month_start, today))
    finance_year = finance.filter(occurred_at__date__range=(year_start, today))

    sales_7d_values = []
    leads_7d_values = []
    for offset in range(6, -1, -1):
        day = today - timedelta(days=offset)
        sales_7d_values.append(float(_money_million_toman(finance.filter(occurred_at__date=day))))
        leads_7d_values.append(leads.filter(created_at__date=day).count())

    branch_rows = list(
        finance_month.values('branch__name')
        .annotate(v=Sum('amount'))
        .order_by('-v')[:5]
    )
    branch_total = sum(Decimal(row['v'] or 0) for row in branch_rows) or Decimal('1')
    branch_sales = [
        {
            'name': row['branch__name'] or 'بدون شعبه',
            'amount_m': Decimal(row['v'] or 0) / MILLION_TOMAN,
            'pct': round(float(Decimal(row['v'] or 0) * 100 / branch_total)),
            'color': COLORS[index % len(COLORS)],
        }
        for index, row in enumerate(branch_rows)
    ]

    source_rows = list(
        leads.values('source').annotate(n=Count('id')).order_by('-n')[:5]
    )
    total_sources = sum(row['n'] for row in source_rows) or 1
    source_labels = dict(ReferralLead.SOURCE)
    lead_sources = [
        {
            'name': source_labels.get(row['source'], row['source'] or 'سایر'),
            'value': row['n'],
            'pct': round(row['n'] * 100 / total_sources),
            'color': COLORS[index % len(COLORS)],
        }
        for index, row in enumerate(source_rows)
    ]

    today_appointments = appointments.filter(appointment_date=today)
    month_appointments = appointments.filter(appointment_date__range=(month_start, today))
    year_appointments = appointments.filter(appointment_date__range=(year_start, today))
    appointment_rows = list(
        today_appointments.values('status').annotate(n=Count('id')).order_by('-n')
    )
    appointment_labels = dict(VisitAppointment.STATUS)
    appointment_mix = [
        {
            'name': appointment_labels.get(row['status'], row['status']),
            'value': row['n'],
            'color': COLORS[index % len(COLORS)],
        }
        for index, row in enumerate(appointment_rows)
    ]

    meetings = MeetingMinute.objects.filter(meeting_date__gte=today - timedelta(days=30))

    return {
        'sales_today_m': _money_million_toman(finance_today),
        'sales_yesterday_m': _money_million_toman(finance_yesterday),
        'sales_month_m': _money_million_toman(finance_month),
        'sales_year_m': _money_million_toman(finance_year),
        'sales_7d': _bar_rows(sales_7d_values),
        'branch_sales': branch_sales,
        'leads_total': leads.count(),
        'leads_today': leads.filter(created_at__date=today).count(),
        'leads_month': leads.filter(created_at__date__range=(month_start, today)).count(),
        'leads_year': leads.filter(created_at__date__range=(year_start, today)).count(),
        'leads_open': leads.filter(status__in=('new', 'contacted', 'appointment', 'visited')).count(),
        'lead_sources': lead_sources,
        'leads_7d': _bar_rows(leads_7d_values),
        'appointments_today': today_appointments.count(),
        'appointments_month': month_appointments.count(),
        'appointments_year': year_appointments.count(),
        'appointment_mix': appointment_mix,
        'arrived_today': today_appointments.filter(status__in=('arrived', 'completed')).count(),
        'won_month': sales.filter(sale_date__gte=month_start, sale_date__lte=today).values('lead_id').distinct().count(),
        'open_tasks': open_tasks.count(),
        'overdue_tasks': open_tasks.filter(due_date__lt=today).count(),
        'meetings_30d': meetings.count(),
        'open_meetings': meetings.filter(status='open').count(),
    }
