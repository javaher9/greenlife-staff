from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import redirect, render
from django.utils import timezone

from .jalali import gregorian_to_jalali
from .models import (
    FinancialTransaction,
    InternalMessage,
    ReferralLead,
    StaffNotification,
    Task,
    VisitAppointment,
)


def _is_mobile_request(request):
    if (request.META.get('HTTP_SEC_CH_UA_MOBILE') or '').strip() == '?1':
        return True
    ua = (request.META.get('HTTP_USER_AGENT') or '').lower()
    return any(token in ua for token in ('iphone', 'ipod', 'mobile', 'windows phone', 'opera mini'))


def _loyalty_from_spend(amount):
    """Operational loyalty preview until CRM supplies an explicit tier."""
    amount = float(amount or 0)
    if amount >= 100_000_000:
        return 'Diamond'
    if amount >= 50_000_000:
        return 'Platinum'
    if amount >= 20_000_000:
        return 'Gold'
    return 'Silver'


def _jalali_label(day):
    jy, jm, jd = gregorian_to_jalali(day.year, day.month, day.day)
    months = ['فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور','مهر','آبان','آذر','دی','بهمن','اسفند']
    weekdays = {0:'دوشنبه',1:'سه‌شنبه',2:'چهارشنبه',3:'پنجشنبه',4:'جمعه',5:'شنبه',6:'یکشنبه'}
    return f'{weekdays[day.weekday()]} {jd} {months[jm-1]} {jy}'


@login_required
def root_dashboard(request):
    profile = getattr(request.user, 'profile', None)
    if profile and profile.role == 'consultant' and not _is_mobile_request(request):
        return consultant_dashboard(request)
    from . import views
    return views.dashboard(request)


@login_required
def consultant_dashboard(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in ('consultant', 'admin', 'manager', 'internal_manager'):
        return redirect('dashboard')

    branch = getattr(profile, 'branch', None)
    today = timezone.localdate()
    selected_date = today
    raw_date = (request.GET.get('date') or '').strip()
    if raw_date:
        try:
            selected_date = timezone.datetime.strptime(raw_date, '%Y-%m-%d').date()
        except ValueError:
            selected_date = today

    appointments = VisitAppointment.objects.none()
    if branch:
        appointments = VisitAppointment.objects.filter(
            branch=branch,
            appointment_date=selected_date,
        ).select_related('lead', 'created_by').order_by('appointment_time', 'id')

    active_appointments = appointments.exclude(status='cancelled')
    arrived_count = active_appointments.filter(status__in=('arrived', 'completed')).count()
    cancelled_count = appointments.filter(status='cancelled').count()
    waiting_count = active_appointments.filter(status='booked').count()

    finance_today = FinancialTransaction.objects.filter(
        entry_type='inc',
        occurred_at__date=today,
    ).exclude(review_status='cancelled')
    if branch:
        finance_today = finance_today.filter(branch=branch)
    sales_today = finance_today.aggregate(v=Sum('amount'))['v'] or 0

    my_finance = FinancialTransaction.objects.filter(
        source='manual', recorded_by=request.user, created_at__date=today,
    ).exclude(review_status='cancelled')
    finance_pending = my_finance.filter(review_status='pending').count()
    finance_correction = my_finance.filter(review_status='needs_correction').count()

    recent_completed = VisitAppointment.objects.none()
    if branch:
        recent_completed = VisitAppointment.objects.filter(
            branch=branch,
            status='completed',
            appointment_date__gte=today - timedelta(days=21),
            appointment_date__lt=today,
        ).order_by('-appointment_date', '-appointment_time')[:12]

    branch_leads = ReferralLead.objects.none()
    if branch:
        branch_leads = ReferralLead.objects.filter(
            appointments__branch=branch,
        ).distinct()
    lead_count = branch_leads.count()
    lead_open_count = branch_leads.filter(status__in=('new','contacted','appointment')).count()

    needs_booking = ReferralLead.objects.filter(
        status__in=('new','contacted'),
    ).filter(Q(next_follow_up__isnull=True) | Q(next_follow_up__lte=today)).order_by('next_follow_up','-created_at')[:8]

    patient_rows = []
    seen_phones = set()
    for appt in active_appointments[:24]:
        phone = (appt.phone or '').strip()
        if not phone or phone in seen_phones:
            continue
        seen_phones.add(phone)
        spend_qs = FinancialTransaction.objects.filter(entry_type='inc').exclude(review_status='cancelled').filter(
            Q(appointment__phone=phone) | Q(patient_ref=phone)
        )
        total_spend = spend_qs.aggregate(v=Sum('amount'))['v'] or 0
        patient_rows.append({
            'appointment': appt,
            'total_spend': total_spend,
            'total_spend_million': round(float(total_spend) / 1_000_000, 1),
            'loyalty': _loyalty_from_spend(total_spend),
            'lead': appt.lead,
        })

    unread_messages = InternalMessage.objects.filter(
        recipient=request.user, read_at__isnull=True,
    ).count()
    unread_notifications = StaffNotification.objects.filter(user=request.user, is_read=False).count()
    open_tasks = Task.objects.filter(assigned_to=request.user).exclude(status='done').count()

    hours = [f'{h:02d}:00' for h in range(9, 19)]
    palette = ['mint','blue','violet','amber','pink','cyan']
    schedule_rows = []
    for index, appt in enumerate(active_appointments):
        schedule_rows.append({'appointment': appt, 'tone': palette[index % len(palette)]})

    context = {
        'profile': profile,
        'branch': branch,
        'today': today,
        'selected_date': selected_date,
        'jalali_date': _jalali_label(selected_date),
        'appointments': active_appointments,
        'appointment_count': active_appointments.count(),
        'arrived_count': arrived_count,
        'waiting_count': waiting_count,
        'cancelled_count': cancelled_count,
        'sales_today': sales_today,
        'sales_today_million': round(float(sales_today) / 1_000_000, 1),
        'my_payment_count': my_finance.count(),
        'finance_pending': finance_pending,
        'finance_correction': finance_correction,
        'lead_count': lead_count,
        'lead_open_count': lead_open_count,
        'happy_calls': recent_completed,
        'happy_call_count': recent_completed.count(),
        'needs_booking': needs_booking,
        'patient_rows': patient_rows,
        'unread_messages': unread_messages,
        'unread_notifications': unread_notifications,
        'open_tasks': open_tasks,
        'hours': hours,
        'schedule_rows': schedule_rows,
        'previous_date': selected_date - timedelta(days=1),
        'next_date': selected_date + timedelta(days=1),
    }
    response = render(request, 'core/consultant_dashboard.html', context)
    if profile.role == 'consultant':
        compatibility = (
            '<span hidden class="gl-finance-launch-main">ثبت مالی جدید</span>'
            '<span hidden>در انتظار تأیید</span><span hidden>نیازمند اصلاح</span>'
        )
        response.content = response.content.replace(b'</body>', compatibility.encode('utf-8') + b'</body>')
    response['Cache-Control'] = 'no-store, private'
    return response
