from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import ReferralLead, ReferralSale, StaffNotification, Task, VisitAppointment

SUCCESS_TYPES = {
    'device': 'پکیج دستگاه',
    'lipolytic': 'لیپولیتیک',
    'daya': 'پکیج دایا',
    'skin_hair': 'پوست و مو',
}
FAILURE_REASONS = {
    'financial': 'مشکل مالی',
    'side_effects': 'عوارض احتمالی',
    'more_review': 'بررسی بیشتر',
    'other': 'سایر',
}


def _consultant(request):
    profile = getattr(request.user, 'profile', None)
    return profile if profile and profile.role == 'consultant' and profile.branch_id else None


def _appointments(profile):
    return VisitAppointment.objects.filter(
        branch_id=profile.branch_id,
        lead__isnull=False,
        source='call_center',
        status__in=('arrived', 'completed'),
    ).select_related('lead', 'lead__assigned_to', 'lead__first_appointment_by', 'branch').order_by('-appointment_date', '-appointment_time')


def _operator_user(lead):
    if lead.first_appointment_by_id:
        return lead.first_appointment_by
    if lead.assigned_to_id:
        return lead.assigned_to.user
    return None


@login_required
def consultant_sales_outcomes(request):
    profile = _consultant(request)
    if not profile:
        messages.error(request, 'این بخش فقط برای مشاور فعال است.')
        return redirect('dashboard')

    appointments = _appointments(profile)
    if request.method == 'POST':
        appointment = get_object_or_404(appointments, pk=request.POST.get('appointment_id'))
        lead = appointment.lead
        result = (request.POST.get('result') or '').strip()
        note = (request.POST.get('note') or '').strip()

        if result == 'success':
            sale_type = (request.POST.get('sale_type') or '').strip()
            if sale_type not in SUCCESS_TYPES:
                messages.error(request, 'نوع فروش موفق را انتخاب کنید.')
                return redirect('consultant_sales_outcomes')
            try:
                amount = Decimal((request.POST.get('amount_toman') or '').replace(',', '').strip())
            except (InvalidOperation, AttributeError):
                amount = Decimal('0')
            if amount <= 0:
                messages.error(request, 'مبلغ فروش را به تومان و بیشتر از صفر وارد کنید.')
                return redirect('consultant_sales_outcomes')

            outcome_note = f"نوع فروش: {SUCCESS_TYPES[sale_type]}"
            if note:
                outcome_note += f" | توضیح مشاور: {note}"
            with transaction.atomic():
                sale, created = ReferralSale.objects.get_or_create(
                    lead=lead,
                    defaults={
                        'sale_date': timezone.localdate(), 'amount': amount,
                        'status': 'approved', 'recorded_by': request.user,
                        'note': outcome_note,
                    },
                )
                if not created:
                    sale.sale_date = timezone.localdate()
                    sale.amount = amount
                    sale.status = 'approved'
                    sale.recorded_by = request.user
                    sale.note = outcome_note
                    sale.save(update_fields=['sale_date', 'amount', 'status', 'recorded_by', 'note', 'updated_at'])
                lead.status = 'won'
                lead.next_follow_up = None
                lead.save(update_fields=['status', 'next_follow_up', 'updated_at'])
                appointment.status = 'completed'
                appointment.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'فروش موفق ثبت شد؛ لید به فروش تبدیل و به مخزن Happy Call اضافه شد.')
            return redirect('consultant_sales_outcomes')

        if result == 'failed':
            reason = (request.POST.get('failure_reason') or '').strip()
            if reason not in FAILURE_REASONS:
                messages.error(request, 'علت فروش ناموفق را انتخاب کنید.')
                return redirect('consultant_sales_outcomes')
            if reason == 'other' and not note:
                messages.error(request, 'برای گزینه «سایر» توضیح الزامی است.')
                return redirect('consultant_sales_outcomes')

            tomorrow = timezone.localdate() + timedelta(days=1)
            reason_label = FAILURE_REASONS[reason]
            detail = f"فروش ناموفق مشاور - {reason_label}"
            if note:
                detail += f" | {note}"
            operator = _operator_user(lead)
            with transaction.atomic():
                lead.status = 'contacted'
                lead.next_follow_up = tomorrow
                lead.notes = ((lead.notes or '') + f"\n[{timezone.localdate()}] {detail}").strip()
                lead.save(update_fields=['status', 'next_follow_up', 'notes', 'updated_at'])
                if operator:
                    Task.objects.create(
                        title=f'پیگیری فروش ناموفق: {lead.full_name}',
                        description=f'{detail}\nتلفن: {lead.phone}\nپیگیری مجدد پس از مراجعه شعبه.',
                        assigned_to=operator, created_by=request.user,
                        due_date=tomorrow, priority='high', status='todo',
                    )
                    StaffNotification.objects.create(
                        user=operator,
                        title='پیگیری فروش ناموفق برای فردا',
                        message=f'{lead.full_name} - {reason_label} - {lead.phone}',
                        notification_type='lead_follow_up', related_date=tomorrow,
                    )
            messages.success(request, 'فروش ناموفق ثبت شد و پیگیری فردا به کال‌سنتر ارجاع شد.')
            return redirect('consultant_sales_outcomes')

        messages.error(request, 'نتیجه مراجعه را مشخص کنید.')
        return redirect('consultant_sales_outcomes')

    pending = appointments.exclude(lead__status='won')[:60]
    happy_calls = ReferralSale.objects.filter(
        recorded_by=request.user, status__in=('approved', 'paid')
    ).select_related('lead').order_by('-sale_date', '-created_at')[:100]
    return render(request, 'core/consultant_sales_outcomes.html', {
        'pending': pending,
        'happy_calls': happy_calls,
        'success_types': SUCCESS_TYPES,
        'failure_reasons': FAILURE_REASONS,
    })
