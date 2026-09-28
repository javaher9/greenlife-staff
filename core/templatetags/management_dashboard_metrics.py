from datetime import date, timedelta
from decimal import Decimal

from django import template
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.jalali import gregorian_to_jalali, jalali_to_gregorian
from core.call_center_identity import call_center_display_name
from django.contrib.auth.models import User

from core.models import (
    Branch,
    DeviceIssue,
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


def _channel_q(channel):
    """Same channel grouping used by Lead Hub; manual/link Instagram stay together."""
    marker=f'[channel:{channel}]'
    if channel=='instagram':
        return (
            Q(notes__icontains='اینستاگرام')
            | Q(notes__icontains='[instagram_page:')
            | Q(source_url__icontains='/instagram/')
        )
    if channel=='beytoote':
        return (
            Q(notes__icontains='[channel:beytoote]')
            | Q(source_url__icontains='/beytoote/')
            | Q(source_url__icontains='bitoteh')
            | Q(source_url__icontains='utm_source=beytoote')
            | Q(notes__icontains='"utm_source":"beytoote"')
        )
    if channel=='aparat':
        return Q(notes__icontains='[channel:aparat]') | Q(source_url__icontains='/aparat/')
    if channel=='telegram':
        return Q(notes__icontains='تلگرام') | Q(source_url__icontains='/telegram/')
    if channel=='bale':
        return Q(notes__icontains='[channel:bale]') | Q(source_url__icontains='/bale/')
    if channel=='website':
        website_q=Q(notes__icontains=marker) | Q(source_url__icontains='greenlifeclinics.com')
        return (
            website_q
            & ~_channel_q('instagram')
            & ~_channel_q('telegram')
            & ~_channel_q('bale')
            & ~_channel_q('beytoote')
            & ~_channel_q('aparat')
        )
    if channel=='crm':
        return Q(notes__icontains=marker) | Q(source_url__icontains='crm')
    if channel=='whatsapp':
        return Q(notes__icontains=marker) | Q(source_url__icontains='whatsapp') | Q(source_url__icontains='wa.me')
    if channel=='campaign':
        return (
            (Q(notes__icontains=marker) | Q(source_url__icontains='utm_campaign='))
            & ~_channel_q('beytoote')
        )
    return Q(pk__in=[])


def _height_rows(rows, value_key='value'):
    peak=max([float(row.get(value_key) or 0) for row in rows] or [0]) or 1
    for row in rows:
        value=float(row.get(value_key) or 0)
        row['height']=max(7,round(value*100/peak)) if value else 4
    return rows


def _dashboard_branches(selected_branch=None, *, include_afsariyeh=True):
    if selected_branch:
        return [selected_branch]
    active=list(Branch.objects.filter(is_active=True).order_by('id'))
    wanted=('نیاوران','پونک','اصفهان','ارومیه','افسریه')
    ordered=[]
    used=set()
    for token in wanted:
        if token=='افسریه' and not include_afsariyeh:
            continue
        for branch in active:
            if branch.pk not in used and token in branch.name:
                ordered.append(branch); used.add(branch.pk); break
    # Do not let auxiliary branches make the executive plaque unreadable.
    return ordered[:5]



def _jalali_label(day):
    jy,jm,jd=gregorian_to_jalali(day.year,day.month,day.day)
    return f'{jm:02d}/{jd:02d}'


def _period_trend(queryset, date_field, start, end, *, sum_field=None, divisor=1):
    rows=(
        queryset.filter(**{f'{date_field}__range':(start,end)})
        .values(date_field)
        .annotate(v=Sum(sum_field) if sum_field else Count('id'))
        .order_by(date_field)
    )
    values={row[date_field]:row['v'] or 0 for row in rows}
    out=[]
    day=start
    while day<=end:
        raw=values.get(day,0)
        value=float(Decimal(raw)/Decimal(str(divisor))) if sum_field else int(raw)
        out.append({'label':_jalali_label(day),'value':value})
        day+=timedelta(days=1)
    return out


def _branch_breakdown(queryset, branches, *, sum_field=None, divisor=1):
    rows=[]
    for index,branch in enumerate(branches):
        branch_qs=queryset.filter(branch=branch)
        raw=(branch_qs.aggregate(v=Sum(sum_field))['v'] or 0) if sum_field else branch_qs.count()
        value=float(Decimal(raw)/Decimal(str(divisor))) if sum_field else int(raw)
        rows.append({'name':branch.name,'value':value,'color':COLORS[index%len(COLORS)]})
    _height_rows(rows)
    return rows


def _operator_breakdown(queryset):
    grouped=list(
        queryset.filter(created_by__isnull=False)
        .values('created_by_id').annotate(value=Count('id')).order_by('-value')
    )
    users={u.pk:u for u in User.objects.filter(pk__in=[r['created_by_id'] for r in grouped])}
    return [
        {'name':call_center_display_name(users.get(row['created_by_id'])) or 'نامشخص','value':row['value']}
        for row in grouped
    ]


def _future_matrix(queryset, branches):
    grouped=list(
        queryset.filter(created_by__isnull=False)
        .values('created_by_id','branch_id').annotate(value=Count('id'))
    )
    users={u.pk:u for u in User.objects.filter(pk__in={r['created_by_id'] for r in grouped})}
    by_user={}
    for row in grouped:
        by_user.setdefault(row['created_by_id'],{})[row['branch_id']]=row['value']
    result=[]
    for user_id,counts in by_user.items():
        segments=[]
        total=0
        for index,branch in enumerate(branches):
            value=int(counts.get(branch.pk,0))
            total+=value
            segments.append({'name':branch.name,'value':value,'color':COLORS[index%len(COLORS)]})
        result.append({'name':call_center_display_name(users.get(user_id)) or 'نامشخص','total':total,'segments':segments})
    result.sort(key=lambda r:(-r['total'],r['name']))
    return result


@register.simple_tag
def management_dashboard_metrics(selected_branch=None):
    """Compact real-data metrics for the manager /live/ command center.

    It deliberately mirrors the branch selector used by branch_live, so the
    executive cards never show a different scope from the rest of the page.
    """
    today = timezone.localdate()
    jy, jm, _ = gregorian_to_jalali(today.year, today.month, today.day)
    month_start = date(*jalali_to_gregorian(jy, jm, 1))
    year_start = date(*jalali_to_gregorian(jy, 1, 1))
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

    # One grouped query per source replaces dozens of per-day queries.
    # This is the hot path for /live/ and materially reduces initial page latency.
    start_30 = today - timedelta(days=29)
    sales_by_day = {
        row['day']: Decimal(row['value'] or 0) / MILLION_TOMAN
        for row in (
            finance.filter(occurred_at__date__range=(start_30, today))
            .annotate(day=TruncDate('occurred_at'))
            .values('day')
            .annotate(value=Sum('amount'))
        )
    }
    leads_by_day = {
        row['day']: row['value']
        for row in (
            leads.filter(created_at__date__range=(start_30, today))
            .annotate(day=TruncDate('created_at'))
            .values('day')
            .annotate(value=Count('id'))
        )
    }

    previous_7_sales = [
        sales_by_day.get(today - timedelta(days=offset), Decimal('0'))
        for offset in range(1, 8)
    ]
    sales_prev7_avg_m = sum(previous_7_sales, Decimal('0')) / Decimal('7')
    sales_today_m = sales_by_day.get(today, Decimal('0'))
    sales_vs_7d_pct = None
    if sales_prev7_avg_m > 0:
        sales_vs_7d_pct = round(
            (float(sales_today_m - sales_prev7_avg_m) * 100) / float(sales_prev7_avg_m),
            1,
        )

    sales_7d_values = []
    leads_7d_values = []
    sales_30d = []
    leads_30d = []
    for offset in range(29, -1, -1):
        day = today - timedelta(days=offset)
        day_sales = float(sales_by_day.get(day, Decimal('0')))
        day_leads = leads_by_day.get(day, 0)
        jy, jm, jd = gregorian_to_jalali(day.year, day.month, day.day)
        label = f'{jm:02d}/{jd:02d}'
        sales_30d.append({'label': label, 'value': day_sales})
        leads_30d.append({'label': label, 'value': day_leads})
        if offset <= 6:
            sales_7d_values.append(day_sales)
            leads_7d_values.append(day_leads)

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

    today_leads_qs = leads.filter(created_at__date=today)
    today_lead_count = today_leads_qs.count()
    today_leads_with_appointment = (
        VisitAppointment.objects
        .filter(lead__in=today_leads_qs)
        .exclude(status='cancelled')
        .values('lead_id').distinct().count()
    )
    lead_to_appointment_today_pct = round(
        today_leads_with_appointment * 100 / max(1, today_lead_count)
    ) if today_lead_count else 0
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

    # Real executive breakdowns used by the three live top plaques.
    sales_branch_rows=[]
    for index, branch in enumerate(_dashboard_branches(selected_branch, include_afsariyeh=True)):
        amount=finance_today.filter(branch=branch).aggregate(v=Sum('amount'))['v'] or 0
        sales_branch_rows.append({
            'name':branch.name,'value_m':Decimal(amount)/MILLION_TOMAN,
            'color':COLORS[index % len(COLORS)],
        })
    _height_rows(sales_branch_rows,'value_m')

    appointment_branch_rows=[]
    for index, branch in enumerate(_dashboard_branches(selected_branch, include_afsariyeh=False)):
        count=today_appointments.filter(branch=branch).exclude(status='cancelled').count()
        appointment_branch_rows.append({
            'name':branch.name,'value':count,'color':COLORS[index % len(COLORS)],
        })
    _height_rows(appointment_branch_rows)

    future_appointments_created_today=(
        appointments.filter(
            created_at__date=today,
            appointment_date__gt=today,
            source='call_center',
        )
        .exclude(status='cancelled')
        .count()
    )

    today_channels=[
        ('instagram','اینستاگرام','#ec4899'),
        ('website','وب‌سایت','#3b82f6'),
        ('beytoote','بیتوته','#f59e0b'),
        ('aparat','آپارات','#06b6d4'),
        ('whatsapp','واتس‌اپ','#22c55e'),
        ('crm','CRM','#8b5cf6'),
        ('telegram','تلگرام','#38bdf8'),
        ('bale','بله','#10b981'),
        ('campaign','کمپین','#f97316'),
    ]
    channel_rows=[]
    claimed=Q(pk__in=[])
    for key,label,color in today_channels:
        q=_channel_q(key)
        count=today_leads_qs.filter(q).count()
        if count:
            channel_rows.append({'key':key,'name':label,'value':count,'color':color})
        claimed |= q
    other_count=today_leads_qs.exclude(claimed).count()
    if other_count:
        channel_rows.append({'key':'other','name':'سایر','value':other_count,'color':'#94a3b8'})
    channel_rows.sort(key=lambda row:row['value'],reverse=True)
    if len(channel_rows)>5:
        visible=channel_rows[:4]
        rest=sum(row['value'] for row in channel_rows[4:])
        visible.append({'key':'other','name':'سایر','value':rest,'color':'#94a3b8'})
        channel_rows=visible
    _height_rows(channel_rows)


    # Rich executive cards. "ماه اخیر" means current Jalali month and
    # "سال اخیر" means current Jalali year; never a rolling 30/365-day shortcut.
    period_ranges={
        'week':(today-timedelta(days=6),today),
        'month':(month_start,today),
        'year':(year_start,today),
    }
    sales_branches=_dashboard_branches(selected_branch,include_afsariyeh=True)
    appt_branches=_dashboard_branches(selected_branch,include_afsariyeh=False)
    executive_cards={}

    future_base=appointments.filter(source='call_center').exclude(status='cancelled').annotate(
        created_day=TruncDate('created_at')
    ).filter(appointment_date__gt=F('created_day'))

    for period_key,(period_start,period_end) in period_ranges.items():
        finance_period=finance.filter(occurred_at__date__range=(period_start,period_end))
        leads_period=leads.filter(created_at__date__range=(period_start,period_end))
        appts_period=appointments.filter(
            appointment_date__range=(period_start,period_end)
        ).exclude(status='cancelled')
        future_period=future_base.filter(created_at__date__range=(period_start,period_end))

        # Sales trend is grouped on the actual transaction day.
        sales_rows=(
            finance_period.annotate(day=TruncDate('occurred_at'))
            .values('day').annotate(v=Sum('amount')).order_by('day')
        )
        sales_map={r['day']:float(Decimal(r['v'] or 0)/MILLION_TOMAN) for r in sales_rows}

        lead_rows=(
            leads_period.annotate(day=TruncDate('created_at'))
            .values('day').annotate(v=Count('id')).order_by('day')
        )
        lead_map={r['day']:int(r['v'] or 0) for r in lead_rows}

        appt_rows=(
            appts_period.values('appointment_date').annotate(v=Count('id')).order_by('appointment_date')
        )
        appt_map={r['appointment_date']:int(r['v'] or 0) for r in appt_rows}

        future_rows=(
            future_period.values('created_day').annotate(v=Count('id')).order_by('created_day')
        )
        future_map={r['created_day']:int(r['v'] or 0) for r in future_rows}

        def build_series(value_map):
            series=[]; day=period_start
            while day<=period_end:
                series.append({'label':_jalali_label(day),'value':value_map.get(day,0)})
                day+=timedelta(days=1)
            return series

        channels=[]
        claimed=Q(pk__in=[])
        for key,label,color in today_channels:
            q=_channel_q(key); value=leads_period.filter(q).count()
            if value:
                channels.append({'name':label,'value':value,'color':color})
            claimed|=q
        other=leads_period.exclude(claimed).count()
        if other:
            channels.append({'name':'سایر','value':other,'color':'#94a3b8'})
        channels.sort(key=lambda r:r['value'],reverse=True)
        if len(channels)>7:
            rest=sum(r['value'] for r in channels[6:])
            channels=channels[:6]+[{'name':'سایر','value':rest,'color':'#94a3b8'}]
        _height_rows(channels)

        referral_sales_period=ReferralSale.objects.filter(
            status__in=('approved','paid'),
            sale_date__range=(period_start,period_end),
        ).select_related('lead__referrer__user')
        network_rows=list(
            referral_sales_period.values('sale_date').annotate(v=Count('id')).order_by('sale_date')
        )
        network_map={r['sale_date']:int(r['v'] or 0) for r in network_rows}
        top_referrers=list(
            referral_sales_period.values(
                'lead__referrer__user__first_name',
                'lead__referrer__user__last_name',
                'lead__referrer__user__username',
            ).annotate(value=Count('id')).order_by('-value')[:6]
        )
        network_people=[]
        for row in top_referrers:
            name=' '.join(x for x in (
                row['lead__referrer__user__first_name'],
                row['lead__referrer__user__last_name'],
            ) if x).strip() or row['lead__referrer__user__username'] or 'بدون نام'
            network_people.append({'name':name,'value':row['value']})

        device_period=DeviceIssue.objects.filter(created_at__date__range=(period_start,period_end))
        device_rows=list(
            device_period.annotate(day=TruncDate('created_at'))
            .values('day').annotate(v=Count('id')).order_by('day')
        )
        device_map={r['day']:int(r['v'] or 0) for r in device_rows}
        device_branch_rows=list(
            device_period.values('branch__name').annotate(value=Count('id')).order_by('-value')[:6]
        )
        device_branches=[
            {'name':r['branch__name'] or 'بدون شعبه','value':r['value'],'color':COLORS[i%len(COLORS)]}
            for i,r in enumerate(device_branch_rows)
        ]
        _height_rows(device_branches)

        executive_cards[period_key]={
            'sales':{
                'trend':build_series(sales_map),
                'branches':_branch_breakdown(finance_period,sales_branches,sum_field='amount',divisor=MILLION_TOMAN),
            },
            'appointments':{
                'trend':build_series(appt_map),
                'branches':_branch_breakdown(appts_period,appt_branches),
                'operators':_operator_breakdown(appts_period.filter(source='call_center')),
            },
            'future':{
                'trend':build_series(future_map),
                'matrix':_future_matrix(future_period,appt_branches),
                'branches':[{'name':b.name,'color':COLORS[i%len(COLORS)]} for i,b in enumerate(appt_branches)],
            },
            'leads':{'trend':build_series(lead_map),'sources':channels},
            'network':{'trend':build_series(network_map),'people':network_people},
            'devices':{
                'trend':build_series(device_map),
                'branches':device_branches,
                'new':device_period.filter(status='new').count(),
                'reviewing':device_period.filter(status='reviewing').count(),
                'resolved':device_period.filter(status='resolved').count(),
            },
        }

        meetings = MeetingMinute.objects.filter(meeting_date__gte=today - timedelta(days=30))

    return {
        'sales_today_m': sales_today_m,
        'sales_yesterday_m': _money_million_toman(finance_yesterday),
        'sales_prev7_avg_m': sales_prev7_avg_m,
        'sales_vs_7d_pct': sales_vs_7d_pct,
        'sales_month_m': _money_million_toman(finance_month),
        'sales_year_m': _money_million_toman(finance_year),
        'sales_7d': _bar_rows(sales_7d_values),
        'sales_30d': sales_30d,
        'branch_sales': branch_sales,
        'sales_branch_today': sales_branch_rows,
        'leads_total': leads.count(),
        'leads_today': today_lead_count,
        'leads_month': leads.filter(created_at__date__range=(month_start, today)).count(),
        'leads_year': leads.filter(created_at__date__range=(year_start, today)).count(),
        'leads_open': leads.filter(status__in=('new', 'contacted', 'appointment', 'visited')).count(),
        'lead_sources': lead_sources,
        'lead_sources_today': channel_rows,
        'leads_7d': _bar_rows(leads_7d_values),
        'leads_30d': leads_30d,
        'today_leads_with_appointment': today_leads_with_appointment,
        'lead_to_appointment_today_pct': lead_to_appointment_today_pct,
        'appointments_today': today_appointments.count(),
        'appointments_month': month_appointments.count(),
        'appointments_year': year_appointments.count(),
        'appointment_mix': appointment_mix,
        'appointment_branches_today': appointment_branch_rows,
        'future_appointments_created_today': future_appointments_created_today,
        'executive_cards': executive_cards,
        'network_sales_today': ReferralSale.objects.filter(status__in=('approved','paid'), sale_date=today).count(),
        'device_open_now': DeviceIssue.objects.exclude(status='resolved').count(),
        'arrived_today': today_appointments.filter(status__in=('arrived', 'completed')).count(),
        'won_month': sales.filter(sale_date__gte=month_start, sale_date__lte=today).values('lead_id').distinct().count(),
        'open_tasks': open_tasks.count(),
        'overdue_tasks': open_tasks.filter(due_date__lt=today).count(),
        'meetings_30d': meetings.count(),
        'open_meetings': meetings.filter(status='open').count(),
    }
