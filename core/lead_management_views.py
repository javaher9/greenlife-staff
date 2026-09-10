from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render
from django.utils import timezone

from .models import EmployeeProfile, ReferralLead, ReferralSale


ALLOWED_ROLES = ('admin', 'manager', 'internal_manager')
STATUS_LABELS = dict(ReferralLead.STATUS)


@login_required
def lead_management_dashboard(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in ALLOWED_ROLES:
        return render(request, 'core/lead_management_forbidden.html', status=403)

    today = timezone.localdate()
    start_week = today - timedelta(days=today.weekday())
    start_month = today.replace(day=1)

    leads = ReferralLead.objects.select_related(
        'assigned_to__user', 'group', 'referrer__user'
    ).prefetch_related('appointments')

    source_filter = (request.GET.get('source') or '').strip()
    status_filter = (request.GET.get('status') or '').strip()
    operator_filter = (request.GET.get('operator') or '').strip()

    filtered = leads
    if source_filter == 'instagram':
        filtered = filtered.filter(group__name='اینستاگرام جدید')
    elif source_filter:
        filtered = filtered.filter(source=source_filter)
    if status_filter:
        filtered = filtered.filter(status=status_filter)
    if operator_filter.isdigit():
        filtered = filtered.filter(assigned_to_id=int(operator_filter))

    total = leads.count()
    today_count = leads.filter(created_at__date=today).count()
    week_count = leads.filter(created_at__date__gte=start_week).count()
    month_count = leads.filter(created_at__date__gte=start_month).count()
    instagram_count = leads.filter(group__name='اینستاگرام جدید').count()
    contacted_count = leads.filter(status__in=('contacted', 'appointment', 'visited', 'won')).count()
    appointment_count = leads.filter(status__in=('appointment', 'visited', 'won')).count()
    won_count = leads.filter(status='won').count()
    conversion = round((won_count * 100 / total), 1) if total else 0

    status_rows = []
    status_counts = dict(leads.values_list('status').annotate(c=Count('id')))
    for key, label in ReferralLead.STATUS:
        count = status_counts.get(key, 0)
        status_rows.append({
            'key': key,
            'label': label,
            'count': count,
            'percent': round(count * 100 / total, 1) if total else 0,
        })

    source_rows = [
        {'label': 'اینستاگرام جدید', 'count': instagram_count},
        {'label': 'لینک‌ها', 'count': leads.filter(source='link').exclude(group__name='اینستاگرام جدید').count()},
        {'label': 'ثبت در پنل', 'count': leads.filter(source='panel').count()},
        {'label': 'QR', 'count': leads.filter(source='qr').count()},
        {'label': 'فایل / Import', 'count': leads.filter(source='import').count()},
    ]
    max_source = max([r['count'] for r in source_rows] or [1]) or 1
    for row in source_rows:
        row['bar'] = round(row['count'] * 100 / max_source, 1)

    operator_rows = []
    operators = EmployeeProfile.objects.filter(
        role='call_center', is_active=True, user__is_active=True
    ).select_related('user')
    for op in operators:
        qs = leads.filter(assigned_to=op)
        op_total = qs.count()
        op_won = qs.filter(status='won').count()
        operator_rows.append({
            'id': op.id,
            'name': op.user.get_full_name() or op.user.username,
            'total': op_total,
            'open': qs.filter(status__in=('new', 'contacted', 'appointment')).count(),
            'appointments': qs.filter(status__in=('appointment', 'visited', 'won')).count(),
            'won': op_won,
            'conversion': round(op_won * 100 / op_total, 1) if op_total else 0,
        })
    operator_rows.sort(key=lambda x: (x['won'], x['appointments'], x['total']), reverse=True)

    sales = ReferralSale.objects.filter(status__in=('approved', 'paid'))
    sales_amount = sales.aggregate(v=Sum('amount'))['v'] or 0
    instagram_sales_amount = sales.filter(lead__group__name='اینستاگرام جدید').aggregate(v=Sum('amount'))['v'] or 0

    recent = filtered.order_by('-created_at')[:100]

    return render(request, 'core/lead_management_dashboard.html', {
        'lead_kpis': {
            'total': total,
            'today': today_count,
            'week': week_count,
            'month': month_count,
            'instagram': instagram_count,
            'contacted': contacted_count,
            'appointments': appointment_count,
            'won': won_count,
            'conversion': conversion,
            'sales_amount': sales_amount,
            'instagram_sales_amount': instagram_sales_amount,
        },
        'status_rows': status_rows,
        'source_rows': source_rows,
        'operator_rows': operator_rows,
        'recent_leads': recent,
        'operators': operators,
        'source_filter': source_filter,
        'status_filter': status_filter,
        'operator_filter': operator_filter,
        'status_choices': ReferralLead.STATUS,
    })
