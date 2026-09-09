import json
from datetime import datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

from django import template
from django.conf import settings
from django.db.models import Count, Sum, Q
from django.utils import timezone

from core.jalali import gregorian_to_jalali, jalali_to_gregorian
from core.models import Branch, EmployeeProfile, FinancialTransaction, ReferralLead, VisitAppointment

register = template.Library()

ZERO = Decimal('0')


def _aware_start(day):
    return timezone.make_aware(datetime.combine(day, time.min))


def _period_bounds(day, period):
    if period == 'yesterday':
        start_day = day - timedelta(days=1)
        return _aware_start(start_day), _aware_start(day), 'دیروز'
    if period == 'week':
        start_day = day - timedelta(days=6)
        return _aware_start(start_day), _aware_start(day + timedelta(days=1)), '۷ روز اخیر'
    jy, jm, _ = gregorian_to_jalali(day.year, day.month, day.day)
    if period == 'month':
        start_day = datetime(*jalali_to_gregorian(jy, jm, 1)).date()
        ny, nm = (jy + 1, 1) if jm == 12 else (jy, jm + 1)
        end_day = datetime(*jalali_to_gregorian(ny, nm, 1)).date()
        return _aware_start(start_day), _aware_start(end_day), 'ماه جاری'
    if period == 'year':
        start_day = datetime(*jalali_to_gregorian(jy, 1, 1)).date()
        end_day = datetime(*jalali_to_gregorian(jy + 1, 1, 1)).date()
        return _aware_start(start_day), _aware_start(end_day), 'سال جاری'
    return _aware_start(day), _aware_start(day + timedelta(days=1)), 'امروز'


def _pct(value, total):
    if not total:
        return 0
    return max(0, min(100, round(float(value or ZERO) * 100 / float(total))))


def _money(value):
    return value or ZERO


def _million_toman_display(value):
    millions = Decimal(str(value or 0)) / Decimal('1000000')
    rendered = f'{millions.quantize(Decimal("0.001")):f}'.rstrip('0').rstrip('.')
    return rendered or '0'


def _clinic_revenue_snapshot(day):
    """Load the real clinic revenue JSON snapshot and normalize it for finance UI charts."""
    data_path = Path(settings.BASE_DIR) / 'core' / 'data' / 'clinic_revenue_timeline.json'
    empty = {
        'available': False, 'grand_total': 0, 'branches': [], 'timeline': [],
        'record_count': 0, 'period_label': 'ماه جاری', 'start_label': '', 'end_label': '',
    }
    try:
        payload = json.loads(data_path.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return empty

    rows = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return empty

    jy, jm, _ = gregorian_to_jalali(day.year, day.month, day.day)
    month_start = datetime(*jalali_to_gregorian(jy, jm, 1)).date()
    next_jy, next_jm = (jy + 1, 1) if jm == 12 else (jy, jm + 1)
    month_end = datetime(*jalali_to_gregorian(next_jy, next_jm, 1)).date()

    totals = {}
    date_values = {}
    accepted = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            row_day = datetime.strptime(str(row.get('date', '')), '%m/%d/%Y').date()
            amount = int(Decimal(str(row.get('total', 0) or 0)))
        except (ValueError, TypeError, ArithmeticError):
            continue
        if not (month_start <= row_day < month_end):
            continue
        clinic = str(row.get('کلینیک') or row.get('clinic') or row.get('branch') or '').strip()
        if not clinic:
            continue
        accepted.append((row_day, clinic, amount))
        totals[clinic] = totals.get(clinic, 0) + amount
        date_values.setdefault(row_day, {})[clinic] = amount

    if not accepted:
        return empty

    palette = {
        'نیاوران': '#8b5cf6',
        'پونک': '#3b82f6',
        'اصفهان': '#16d888',
        'ارومیه': '#f59e0b',
    }
    fallback_colors = ['#22d3ee', '#ec4899', '#a3e635', '#f97316', '#c084fc']
    grand_total = sum(totals.values())
    max_branch_total = max(totals.values()) or 1
    branches = []
    for idx, (name, total) in enumerate(sorted(totals.items(), key=lambda item: item[1], reverse=True)):
        branches.append({
            'name': name,
            'total': total,
            'total_display': _million_toman_display(total),
            'pct': round((total * 100 / grand_total), 1) if grand_total else 0,
            'relative': round((total * 100 / max_branch_total), 1),
            'color': palette.get(name, fallback_colors[idx % len(fallback_colors)]),
        })

    timeline = []
    for row_day in sorted(date_values):
        rjy, rjm, rjd = gregorian_to_jalali(row_day.year, row_day.month, row_day.day)
        timeline.append({
            'date': row_day.isoformat(),
            'label': f'{rjm:02d}/{rjd:02d}',
            'values': date_values[row_day],
        })

    first_day = min(x[0] for x in accepted)
    last_day = max(x[0] for x in accepted)
    _, first_month, first_dom = gregorian_to_jalali(first_day.year, first_day.month, first_day.day)
    _, last_month, last_dom = gregorian_to_jalali(last_day.year, last_day.month, last_day.day)
    return {
        'available': True,
        'grand_total': grand_total,
        'grand_total_display': _million_toman_display(grand_total),
        'branches': branches,
        'timeline': timeline,
        'chart_data': {'branches': branches, 'timeline': timeline},
        'record_count': len(accepted),
        'period_label': f'{jy}/{jm:02d}',
        'start_label': f'{first_month:02d}/{first_dom:02d}',
        'end_label': f'{last_month:02d}/{last_dom:02d}',
    }


def _apply_transaction_filters(qs, branch, flower_id, source, service):
    if branch:
        qs = qs.filter(branch=branch)
    if flower_id:
        qs = qs.filter(call_center_owner_id=flower_id)
    if source:
        if source == 'direct':
            qs = qs.filter(appointment__isnull=True)
        else:
            qs = qs.filter(appointment__lead__source=source)
    if service:
        qs = qs.filter(sale_reason=service)
    return qs


@register.simple_tag(takes_context=True)
def finance_intelligence(context):
    request = context.get('request')
    user = getattr(request, 'user', None)
    day = context.get('selected') or timezone.localdate()
    period = (request.GET.get('period') if request else '') or 'today'
    if period not in {'today', 'yesterday', 'week', 'month', 'year'}:
        period = 'today'
    start, end, period_label = _period_bounds(day, period)

    role = getattr(getattr(user, 'profile', None), 'role', '')
    branch = None
    requested_branch = (request.GET.get('branch') if request else '') or ''
    if role == 'manager':
        branch = getattr(user.profile, 'branch', None)
    elif requested_branch.isdigit():
        branch = Branch.objects.filter(pk=int(requested_branch), is_active=True).first()

    flower_raw = (request.GET.get('flower') if request else '') or ''
    flower_id = int(flower_raw) if flower_raw.isdigit() else None
    source = (request.GET.get('source') if request else '') or ''
    valid_sources = {code for code, _ in ReferralLead.SOURCE} | {'direct'}
    if source not in valid_sources:
        source = ''
    service = (request.GET.get('service') if request else '') or ''
    valid_services = {code for code, _ in FinancialTransaction.SALE_REASON}
    if service not in valid_services:
        service = ''

    income = FinancialTransaction.objects.filter(
        review_status='approved', entry_type='inc', occurred_at__gte=start, occurred_at__lt=end,
    ).select_related('branch', 'call_center_owner', 'appointment__lead')
    income = _apply_transaction_filters(income, branch, flower_id, source, service)

    total = _money(income.aggregate(v=Sum('amount'))['v'])
    count = income.count()
    avg_invoice = (total / count) if count else ZERO

    # Leads and appointments use the same visible dimensions where the relation exists.
    leads = ReferralLead.objects.filter(created_at__gte=start, created_at__lt=end)
    if source and source != 'direct':
        leads = leads.filter(source=source)
    if flower_id:
        leads = leads.filter(first_appointment_by_id=flower_id)
    if branch:
        leads = leads.filter(appointments__branch=branch).distinct()
    lead_count = leads.count() if source != 'direct' else 0

    appointments = VisitAppointment.objects.filter(
        appointment_date__gte=start.date(), appointment_date__lt=end.date(),
    )
    if branch:
        appointments = appointments.filter(branch=branch)
    if flower_id:
        appointments = appointments.filter(Q(lead__first_appointment_by_id=flower_id) | Q(created_by_id=flower_id))
    if source and source != 'direct':
        appointments = appointments.filter(lead__source=source)
    appointment_count = appointments.count()
    visit_count = appointments.filter(status__in=('arrived', 'completed')).count()
    conversion = round((count * 100 / lead_count), 1) if lead_count else 0
    revenue_per_lead = (total / lead_count) if lead_count else ZERO

    # Last 7 calendar days, retaining all selected non-date dimensions.
    trend = []
    trend_max = ZERO
    for offset in range(6, -1, -1):
        d = day - timedelta(days=offset)
        ds, de = _aware_start(d), _aware_start(d + timedelta(days=1))
        q = FinancialTransaction.objects.filter(
            review_status='approved', entry_type='inc', occurred_at__gte=ds, occurred_at__lt=de,
        )
        q = _apply_transaction_filters(q, branch, flower_id, source, service)
        amount = _money(q.aggregate(v=Sum('amount'))['v'])
        trend_max = max(trend_max, amount)
        trend.append({'date': d, 'amount': amount, 'count': q.count()})
    trend_den = trend_max or Decimal('1')
    for row in trend:
        row['height'] = max(3, _pct(row['amount'], trend_den)) if row['amount'] else 2

    # Branch distribution.
    branch_rows = list(income.values('branch__name').annotate(total=Sum('amount'), count=Count('id')).order_by('-total'))
    branch_colors = ['#16d888', '#3b82f6', '#8b5cf6', '#f59e0b', '#ec4899', '#22d3ee']
    for idx, row in enumerate(branch_rows):
        row['total'] = _money(row['total'])
        row['pct'] = _pct(row['total'], total)
        row['color'] = branch_colors[idx % len(branch_colors)]
        row['label'] = row['branch__name'] or 'بدون شعبه'
    branch_donut = branch_rows[0]['pct'] if branch_rows else 0

    # Lead source distribution for approved income.
    source_rows = []
    source_defs = list(ReferralLead.SOURCE) + [('direct', 'مراجعه مستقیم')]
    source_colors = ['#10d39a', '#2f8cff', '#8b5cf6', '#f59e0b', '#ec4899', '#94a3b8']
    for idx, (code, label) in enumerate(source_defs):
        sq = income
        if code == 'direct':
            sq = sq.filter(appointment__isnull=True)
        else:
            sq = sq.filter(appointment__lead__source=code)
        amount = _money(sq.aggregate(v=Sum('amount'))['v'])
        if amount or (source == code):
            source_rows.append({'code': code, 'label': label, 'total': amount, 'pct': _pct(amount, total), 'color': source_colors[idx % len(source_colors)]})
    source_rows.sort(key=lambda x: x['total'], reverse=True)
    source_donut = source_rows[0]['pct'] if source_rows else 0

    # Service distribution.
    service_rows = []
    for code, label in FinancialTransaction.SALE_REASON:
        sq = income.filter(sale_reason=code)
        amount = _money(sq.aggregate(v=Sum('amount'))['v'])
        if amount or service == code:
            service_rows.append({'code': code, 'label': label, 'total': amount, 'pct': _pct(amount, total)})
    service_rows.sort(key=lambda x: x['total'], reverse=True)

    # Matrix: flower x branch, using the selected period and remaining filters.
    matrix_base = FinancialTransaction.objects.filter(
        review_status='approved', entry_type='inc', occurred_at__gte=start, occurred_at__lt=end,
        call_center_owner_id__isnull=False,
    )
    if source:
        if source == 'direct':
            matrix_base = matrix_base.filter(appointment__isnull=True)
        else:
            matrix_base = matrix_base.filter(appointment__lead__source=source)
    if service:
        matrix_base = matrix_base.filter(sale_reason=service)
    if branch:
        matrix_base = matrix_base.filter(branch=branch)
    if flower_id:
        matrix_base = matrix_base.filter(call_center_owner_id=flower_id)

    flowers = list(EmployeeProfile.objects.filter(
        role='call_center', is_active=True, user__is_active=True,
    ).select_related('user').order_by('user__first_name', 'user__last_name'))
    if flower_id:
        flowers = [f for f in flowers if f.user_id == flower_id]
    branches = list(Branch.objects.filter(is_active=True).order_by('name'))
    if branch:
        branches = [b for b in branches if b.pk == branch.pk]
    grouped = matrix_base.values('call_center_owner_id', 'branch_id').annotate(total=Sum('amount'))
    matrix_values = {(r['call_center_owner_id'], r['branch_id']): _money(r['total']) for r in grouped}
    matrix_rows = []
    for flower in flowers:
        cells = []
        row_total = ZERO
        for b in branches:
            val = matrix_values.get((flower.user_id, b.pk), ZERO)
            row_total += val
            cells.append({'branch': b, 'total': val})
        matrix_rows.append({'flower': flower, 'cells': cells, 'total': row_total})

    # Alerts focus on exceptions and concentration, not generic prose.
    alerts = []
    top_tx = income.order_by('-amount').first()
    if top_tx and total and _pct(top_tx.amount, total) >= 70 and count > 1:
        alerts.append({'level': 'warn', 'text': f'{_pct(top_tx.amount, total)}٪ درآمد این بازه از یک تراکنش تأمین شده؛ تمرکز فروش بالاست.'})
    if branch_rows and branch_rows[0]['pct'] >= 90 and len(branch_rows) > 1:
        alerts.append({'level': 'info', 'text': f"{branch_rows[0]['pct']}٪ درآمد مربوط به شعبه {branch_rows[0]['label']} است."})
    direct_amount = next((x['total'] for x in source_rows if x['code'] == 'direct'), ZERO)
    direct_pct = _pct(direct_amount, total)
    if direct_pct >= 60 and total:
        alerts.append({'level': 'warn', 'text': f'{direct_pct}٪ فروش به مراجعه مستقیم نسبت داده شده؛ کیفیت ثبت منشأ لید بررسی شود.'})
    if not alerts:
        alerts.append({'level': 'ok', 'text': 'در داده‌های این بازه تمرکز یا ناهنجاری برجسته‌ای دیده نشد.'})

    # Recent filtered transactions for the lower ledger/card.
    entries = FinancialTransaction.objects.filter(source='manual').select_related(
        'branch', 'recorded_by', 'call_center_owner', 'appointment__lead__group',
    )
    if branch:
        entries = entries.filter(branch=branch)
    if flower_id:
        entries = entries.filter(call_center_owner_id=flower_id)
    if source:
        entries = entries.filter(appointment__isnull=True) if source == 'direct' else entries.filter(appointment__lead__source=source)
    if service:
        entries = entries.filter(sale_reason=service)

    external_revenue = _clinic_revenue_snapshot(day)

    return {
        'period': period, 'period_label': period_label, 'start': start, 'end': end,
        'branch': branch, 'flower_id': flower_id, 'source': source, 'service': service,
        'branches': Branch.objects.filter(is_active=True).order_by('name'),
        'flowers': EmployeeProfile.objects.filter(role='call_center', is_active=True, user__is_active=True).select_related('user').order_by('user__first_name', 'user__last_name'),
        'source_options': source_defs, 'service_options': FinancialTransaction.SALE_REASON,
        'total': total, 'count': count, 'avg_invoice': avg_invoice,
        'lead_count': lead_count, 'appointment_count': appointment_count, 'visit_count': visit_count,
        'conversion': conversion, 'revenue_per_lead': revenue_per_lead,
        'trend': trend, 'branch_rows': branch_rows, 'branch_donut': branch_donut,
        'source_rows': source_rows, 'source_donut': source_donut, 'service_rows': service_rows,
        'matrix_branches': branches, 'matrix_rows': matrix_rows,
        'alerts': alerts, 'entries': entries.order_by('-occurred_at', '-id')[:60],
        'external_revenue': external_revenue,
    }
