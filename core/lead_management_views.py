from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.shortcuts import render
from django.utils import timezone

from .models import EmployeeProfile, ReferralLead, ReferralSale


ALLOWED_ROLES = ('admin', 'manager', 'internal_manager')
OPEN_STATUSES = ('new', 'contacted', 'appointment')


def _channel_q(channel):
    marker = f'[channel:{channel}]'
    if channel == 'instagram':
        return Q(group__name='اینستاگرام جدید') | Q(notes__icontains='[channel:instagram]')
    if channel == 'website':
        return Q(notes__icontains=marker) | Q(source_url__icontains='greenlifeclinics.com') & ~Q(source_url__icontains='/instagram/')
    if channel == 'crm':
        return Q(notes__icontains=marker) | Q(source_url__icontains='crm')
    if channel == 'whatsapp':
        return Q(notes__icontains=marker) | Q(source_url__icontains='whatsapp') | Q(source_url__icontains='wa.me')
    if channel == 'campaign':
        return Q(notes__icontains=marker) | Q(source_url__icontains='utm_campaign=')
    return Q()


def _channel_counts(leads):
    channels = [
        ('instagram', 'اینستاگرام', '#ec4899'),
        ('website', 'وب‌سایت', '#3b82f6'),
        ('crm', 'CRM', '#8b5cf6'),
        ('whatsapp', 'واتس‌اپ', '#22c55e'),
        ('campaign', 'کمپین / UTM', '#f59e0b'),
    ]
    claimed = Q(pk__in=[])
    rows = []
    for key, label, color in channels:
        q = _channel_q(key)
        count = leads.filter(q).count()
        rows.append({'key': key, 'label': label, 'count': count, 'color': color})
        claimed |= q
    rows.extend([
        {'key': 'panel', 'label': 'ثبت در پنل', 'count': leads.filter(source='panel').count(), 'color': '#06b6d4'},
        {'key': 'qr', 'label': 'QR', 'count': leads.filter(source='qr').count(), 'color': '#14b8a6'},
        {'key': 'import', 'label': 'Import', 'count': leads.filter(source='import').count(), 'color': '#64748b'},
        {'key': 'other', 'label': 'سایر / قدیمی', 'count': leads.exclude(claimed).filter(source='link').count(), 'color': '#94a3b8'},
    ])
    max_count = max([row['count'] for row in rows] or [1]) or 1
    for row in rows:
        row['bar'] = round(row['count'] * 100 / max_count, 1)
    return rows


@login_required
def lead_management_dashboard(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in ALLOWED_ROLES:
        return render(request, 'core/lead_management_forbidden.html', status=403)

    now = timezone.now()
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
    if source_filter in ('instagram', 'website', 'crm', 'whatsapp', 'campaign'):
        filtered = filtered.filter(_channel_q(source_filter))
    elif source_filter in ('panel', 'qr', 'import', 'link'):
        filtered = filtered.filter(source=source_filter)
    if status_filter:
        filtered = filtered.filter(status=status_filter)
    if operator_filter.isdigit():
        filtered = filtered.filter(assigned_to_id=int(operator_filter))

    total = leads.count()
    today_count = leads.filter(created_at__date=today).count()
    week_count = leads.filter(created_at__date__gte=start_week).count()
    month_count = leads.filter(created_at__date__gte=start_month).count()
    contacted_count = leads.filter(status__in=('contacted', 'appointment', 'visited', 'won')).count()
    appointment_count = leads.filter(status__in=('appointment', 'visited', 'won')).count()
    won_count = leads.filter(status='won').count()
    conversion = round((won_count * 100 / total), 1) if total else 0
    contact_rate = round((contacted_count * 100 / total), 1) if total else 0

    unassigned_count = leads.filter(assigned_to__isnull=True, status__in=OPEN_STATUSES).count()
    overdue_count = leads.filter(status__in=OPEN_STATUSES, next_follow_up__lt=today).count()
    untouched_count = leads.filter(status='new', created_at__lt=now - timedelta(hours=2)).count()
    duplicate_phones = (
        leads.exclude(phone='').values('phone').annotate(c=Count('id')).filter(c__gt=1).count()
    )

    status_counts = {row['status']: row['c'] for row in leads.values('status').annotate(c=Count('id'))}
    status_rows = []
    for key, label in ReferralLead.STATUS:
        count = status_counts.get(key, 0)
        status_rows.append({
            'key': key,
            'label': label,
            'count': count,
            'percent': round(count * 100 / total, 1) if total else 0,
        })

    source_rows = _channel_counts(leads)

    operator_rows = []
    operators = EmployeeProfile.objects.filter(
        role='call_center', is_active=True, user__is_active=True
    ).select_related('user')
    for op in operators:
        qs = leads.filter(assigned_to=op)
        op_total = qs.count()
        op_won = qs.filter(status='won').count()
        op_contacted = qs.filter(status__in=('contacted', 'appointment', 'visited', 'won')).count()
        operator_rows.append({
            'id': op.id,
            'name': op.user.get_full_name() or op.user.username,
            'total': op_total,
            'new': qs.filter(status='new').count(),
            'open': qs.filter(status__in=OPEN_STATUSES).count(),
            'overdue': qs.filter(status__in=OPEN_STATUSES, next_follow_up__lt=today).count(),
            'appointments': qs.filter(status__in=('appointment', 'visited', 'won')).count(),
            'won': op_won,
            'contact_rate': round(op_contacted * 100 / op_total, 1) if op_total else 0,
            'conversion': round(op_won * 100 / op_total, 1) if op_total else 0,
        })
    operator_rows.sort(key=lambda x: (x['won'], x['appointments'], x['total']), reverse=True)

    group_rows = list(
        leads.exclude(group__isnull=True)
        .values('group__name')
        .annotate(count=Count('id'))
        .order_by('-count')[:12]
    )

    sales = ReferralSale.objects.filter(status__in=('approved', 'paid'))
    sales_amount = sales.aggregate(v=Sum('amount'))['v'] or 0
    instagram_sales_amount = sales.filter(lead__in=leads.filter(_channel_q('instagram'))).aggregate(v=Sum('amount'))['v'] or 0
    website_sales_amount = sales.filter(lead__in=leads.filter(_channel_q('website'))).aggregate(v=Sum('amount'))['v'] or 0

    recent = filtered.order_by('-created_at')[:150]
    attention = leads.filter(
        Q(assigned_to__isnull=True) |
        Q(status='new', created_at__lt=now - timedelta(hours=2)) |
        Q(status__in=OPEN_STATUSES, next_follow_up__lt=today)
    ).distinct().order_by('created_at')[:20]

    integration_rows = [
        {'name': 'Instagram Form', 'state': 'connected', 'detail': 'فرم فعلی مستقیماً وارد ReferralLead می‌شود.'},
        {'name': 'Website', 'state': 'ready', 'detail': 'برای اتصال فرم سایت به ورودی یکپارچه آماده است.'},
        {'name': 'CRM', 'state': 'ready', 'detail': 'وب‌هوک/API ورودی برای اتصال CRM طراحی شده است.'},
        {'name': 'WhatsApp / Campaigns', 'state': 'ready', 'detail': 'قابل اتصال با source و UTM مستقل.'},
    ]

    return render(request, 'core/lead_management_dashboard.html', {
        'lead_kpis': {
            'total': total,
            'today': today_count,
            'week': week_count,
            'month': month_count,
            'contacted': contacted_count,
            'appointments': appointment_count,
            'won': won_count,
            'conversion': conversion,
            'contact_rate': contact_rate,
            'unassigned': unassigned_count,
            'overdue': overdue_count,
            'untouched': untouched_count,
            'duplicates': duplicate_phones,
            'sales_amount': sales_amount,
            'instagram_sales_amount': instagram_sales_amount,
            'website_sales_amount': website_sales_amount,
        },
        'status_rows': status_rows,
        'source_rows': source_rows,
        'group_rows': group_rows,
        'operator_rows': operator_rows,
        'recent_leads': recent,
        'attention_leads': attention,
        'integration_rows': integration_rows,
        'operators': operators,
        'source_filter': source_filter,
        'status_filter': status_filter,
        'operator_filter': operator_filter,
        'status_choices': ReferralLead.STATUS,
    })
