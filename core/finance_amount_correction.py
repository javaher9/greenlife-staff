from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import AuditLog, FinancialTransaction, StaffNotification


def _role(user):
    profile = getattr(user, 'profile', None)
    return getattr(profile, 'role', '')


def _request_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None


def finance_entry_review_with_amount(request, pk, action):
    """Finance review with an in-place, audited amount correction flow.

    The existing correction button posts here with no corrected_amount and opens
    a focused editor. Saving the editor updates the same transaction, preserving
    its identity and all attribution links while recording old/new values in AuditLog.
    """
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())

    role = _role(request.user)
    if role not in ('admin', 'manager', 'internal_manager'):
        raise PermissionDenied('دسترسی مالی مجاز نیست.')

    entry = get_object_or_404(FinancialTransaction, pk=pk, source='manual')
    if role == 'manager' and entry.branch_id != getattr(request.user.profile, 'branch_id', None):
        messages.error(request, 'این تراکنش مربوط به شعبه شما نیست.')
        return redirect('finance_dashboard')

    if request.method != 'POST':
        return redirect('finance_dashboard')

    if action == 'correction':
        raw_amount = (request.POST.get('corrected_amount') or '').replace(',', '').replace('٬', '').strip()
        if not raw_amount:
            return render(request, 'core/finance_amount_correction.html', {'entry': entry})
        try:
            new_amount = Decimal(raw_amount)
        except (InvalidOperation, ValueError):
            new_amount = Decimal('0')
        if new_amount <= 0:
            messages.error(request, 'مبلغ صحیح باید بیشتر از صفر باشد.')
            return render(request, 'core/finance_amount_correction.html', {'entry': entry, 'entered_amount': raw_amount})

        old_amount = entry.amount
        note = (request.POST.get('review_note') or '').strip()[:300]
        with transaction.atomic():
            entry.amount = new_amount
            entry.review_status = 'approved'
            entry.reviewed_by = request.user
            entry.reviewed_at = timezone.now()
            entry.review_note = note or f'اصلاح مبلغ از {old_amount} به {new_amount}'
            entry.save(update_fields=['amount', 'review_status', 'reviewed_by', 'reviewed_at', 'review_note'])
            AuditLog.objects.create(
                actor=request.user,
                action='finance_amount_correction',
                path=request.path,
                method='POST',
                object_type='FinancialTransaction',
                object_id=str(entry.pk),
                summary=f'اصلاح مبلغ تراکنش {entry.person_name}: {old_amount} → {new_amount}'[:250],
                metadata={
                    'old_amount': str(old_amount),
                    'new_amount': str(new_amount),
                    'review_status': 'approved',
                    'note': note,
                },
                ip_address=_request_ip(request),
            )
            if entry.recorded_by_id and entry.recorded_by_id != request.user.pk:
                StaffNotification.objects.create(
                    user=entry.recorded_by,
                    title='اصلاح مبلغ ثبت مالی',
                    message=f'مبلغ تراکنش {entry.person_name} توسط مدیر اصلاح و تأیید شد.',
                    notification_type='finance_review',
                    related_date=timezone.localdate(),
                )
        messages.success(request, 'مبلغ تراکنش اصلاح و ثبت شد؛ مبلغ قبلی در سابقه حسابرسی محفوظ است.')
        return redirect('finance_dashboard')

    status_map = {'approve': 'approved', 'cancel': 'cancelled'}
    if action not in status_map:
        messages.error(request, 'عملیات نامعتبر است.')
        return redirect('finance_dashboard')

    before = entry.review_status
    entry.review_status = status_map[action]
    entry.reviewed_by = request.user
    entry.reviewed_at = timezone.now()
    entry.review_note = (request.POST.get('review_note') or '').strip()[:300]
    entry.save(update_fields=['review_status', 'reviewed_by', 'reviewed_at', 'review_note'])
    AuditLog.objects.create(
        actor=request.user,
        action='finance_review',
        path=request.path,
        method='POST',
        object_type='FinancialTransaction',
        object_id=str(entry.pk),
        summary=f'وضعیت مالی از {before} به {entry.review_status}'[:250],
        metadata={'before': before, 'after': entry.review_status},
        ip_address=_request_ip(request),
    )
    if entry.recorded_by_id:
        StaffNotification.objects.create(
            user=entry.recorded_by,
            title='نتیجه بررسی ثبت مالی',
            message=f'تراکنش {entry.person_name} به وضعیت «{entry.get_review_status_display()}» تغییر کرد.',
            notification_type='finance_review',
            related_date=timezone.localdate(),
        )
    messages.success(request, 'وضعیت تراکنش به‌روزرسانی شد.')
    return redirect('finance_dashboard')


def install_finance_amount_correction():
    # AppConfig.ready runs before URLconf resolution. Replacing the view here
    # keeps the public URL/name unchanged and avoids touching unrelated finance UI.
    from . import views
    views.finance_entry_review = finance_entry_review_with_amount
