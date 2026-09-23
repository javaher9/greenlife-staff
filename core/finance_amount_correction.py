from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .models import AuditLog, Branch, FinancialTransaction, StaffNotification

MILLION_TOMAN_IN_RIAL = Decimal('10000000')


def _role(user):
    profile = getattr(user, 'profile', None)
    return getattr(profile, 'role', '')


def _request_ip(request):
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None


def _million_toman(amount):
    return Decimal(amount or 0) / MILLION_TOMAN_IN_RIAL


def finance_entry_review_with_amount(request, pk, action):
    """Finance review with an in-place, audited amount correction flow.

    Managers enter correction amounts in *million toman* (e.g. 44 means
    44,000,000 toman). FinancialTransaction keeps its existing internal rial
    storage, so the entered value is converted exactly once before saving.
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
        current_amount_million = _million_toman(entry.amount)
        payment_methods = [
            ('Pos S','Pos S'),('Pos H','Pos H'),('CC P','CC P'),
            ('CC D','CC D'),('CC S','CC S'),('LINK','LINK'),('Cash','نقدی'),
        ]
        branches = Branch.objects.filter(is_active=True).order_by('name')
        context = {
            'entry': entry,
            'current_amount_million': current_amount_million,
            'payment_methods': payment_methods,
            'entry_types': FinancialTransaction.ENTRY_TYPE,
            'sale_origins': FinancialTransaction.SALE_ORIGIN,
            'sale_reasons': FinancialTransaction.SALE_REASON,
            'cash_currencies': FinancialTransaction.CASH_CURRENCY,
            'branches': branches,
        }
        raw_amount = (request.POST.get('corrected_amount') or '').replace(',', '').replace('٬', '').strip()
        if not raw_amount:
            return render(request, 'core/finance_amount_correction.html', context)

        try:
            entered_million = Decimal(raw_amount)
        except (InvalidOperation, ValueError):
            entered_million = Decimal('0')
        if entered_million <= 0:
            messages.error(request, 'مبلغ صحیح باید بیشتر از صفر باشد.')
            context['entered_amount'] = raw_amount
            return render(request, 'core/finance_amount_correction.html', context)

        entry_type=(request.POST.get('entry_type') or '').strip()
        payment_method=(request.POST.get('payment_method') or '').strip()
        sale_origin=(request.POST.get('sale_origin') or '').strip()
        sale_reason=(request.POST.get('sale_reason') or '').strip()
        branch_id=(request.POST.get('branch_id') or '').strip()
        person_name=(request.POST.get('person_name') or '').strip()[:160]
        service=(request.POST.get('service') or '').strip()[:160]
        account_heading=(request.POST.get('account_heading') or '').strip()[:120]
        terminal_or_payee=(request.POST.get('terminal_or_payee') or '').strip()[:160]
        tracking_number=(request.POST.get('tracking_number') or '').strip()[:100]
        destination_card=(request.POST.get('destination_card') or '').strip()[:80]
        description=(request.POST.get('description') or '').strip()
        cash_currency=(request.POST.get('cash_currency') or '').strip()

        valid_entry_types=dict(FinancialTransaction.ENTRY_TYPE)
        valid_payment_methods=dict(payment_methods)
        valid_sale_origins=dict(FinancialTransaction.SALE_ORIGIN)
        valid_sale_reasons=dict(FinancialTransaction.SALE_REASON)
        valid_cash_currencies=dict(FinancialTransaction.CASH_CURRENCY)

        errors=[]
        if entry_type not in valid_entry_types:
            errors.append('نوع ثبت معتبر نیست.')
        if payment_method not in valid_payment_methods:
            errors.append('روش پرداخت معتبر نیست.')
        if sale_origin and sale_origin not in valid_sale_origins:
            errors.append('مبدأ فروش معتبر نیست.')
        if sale_reason and sale_reason not in valid_sale_reasons:
            errors.append('علت فروش معتبر نیست.')
        if not person_name:
            errors.append('نام فرد نمی‌تواند خالی باشد.')
        if payment_method=='CC P' and not terminal_or_payee:
            errors.append('برای CC P نام شخص دریافت‌کننده الزامی است.')

        selected_branch=entry.branch
        if entry.appointment_id:
            # Appointment attribution is authoritative; do not let an edit break branch/source linkage.
            selected_branch=entry.appointment.branch
            sale_origin='afsariyeh'
        else:
            if branch_id:
                selected_branch=branches.filter(pk=int(branch_id)).first() if branch_id.isdigit() else None
                if not selected_branch:
                    errors.append('شعبه انتخاب‌شده معتبر نیست.')
            else:
                selected_branch=None

        cash_amount=None
        cash_exchange_rate=None
        if payment_method=='Cash':
            if cash_currency not in valid_cash_currencies:
                errors.append('ارز نقدی را انتخاب کنید.')
            raw_cash=(request.POST.get('cash_amount') or '').replace(',','').replace('٬','').strip()
            raw_rate=(request.POST.get('cash_exchange_rate') or '').replace(',','').replace('٬','').strip()
            try:
                cash_amount=Decimal(raw_cash) if raw_cash else None
            except (InvalidOperation,ValueError):
                cash_amount=None
                errors.append('مبلغ نقدی معتبر نیست.')
            try:
                cash_exchange_rate=Decimal(raw_rate) if raw_rate else None
            except (InvalidOperation,ValueError):
                cash_exchange_rate=None
                errors.append('نرخ تبدیل معتبر نیست.')
            if cash_currency=='IRR' and cash_amount is None:
                cash_amount=entered_million * MILLION_TOMAN_IN_RIAL
            elif cash_currency!='IRR' and (cash_amount is None or cash_amount<=0):
                errors.append('برای وجه نقد ارزی، مبلغ ارز را وارد کنید.')
            if cash_exchange_rate is not None and cash_exchange_rate<=0:
                errors.append('نرخ تبدیل باید بیشتر از صفر باشد.')
        else:
            cash_currency=''

        if errors:
            for error in errors:
                messages.error(request,error)
            context.update({
                'entered_amount':raw_amount,
                'posted':request.POST,
            })
            return render(request,'core/finance_amount_correction.html',context)

        new_amount=entered_million*MILLION_TOMAN_IN_RIAL
        note=(request.POST.get('review_note') or '').strip()[:300]
        tracked_fields=[
            'amount','entry_type','payment_method','sale_origin','sale_reason','branch_id',
            'person_name','service','account_heading','terminal_or_payee','tracking_number',
            'destination_card','description','cash_currency','cash_amount','cash_exchange_rate',
        ]
        before={field:str(getattr(entry,field) if getattr(entry,field) is not None else '') for field in tracked_fields}

        with transaction.atomic():
            entry.amount=new_amount
            entry.entry_type=entry_type
            entry.payment_method=payment_method
            entry.sale_origin=sale_origin
            entry.sale_reason=sale_reason
            entry.branch=selected_branch
            entry.person_name=person_name
            entry.service=service
            entry.account_heading=account_heading
            entry.terminal_or_payee=terminal_or_payee
            entry.tracking_number=tracking_number
            entry.destination_card=destination_card
            entry.description=description
            entry.cash_currency=cash_currency
            entry.cash_amount=cash_amount
            entry.cash_exchange_rate=cash_exchange_rate
            entry.review_status='approved'
            entry.reviewed_by=request.user
            entry.reviewed_at=timezone.now()
            entry.review_note=note or 'اصلاح کامل تراکنش توسط مدیر'
            entry.save(update_fields=[
                'amount','entry_type','payment_method','sale_origin','sale_reason','branch',
                'person_name','service','account_heading','terminal_or_payee','tracking_number',
                'destination_card','description','cash_currency','cash_amount','cash_exchange_rate',
                'review_status','reviewed_by','reviewed_at','review_note',
            ])
            after={field:str(getattr(entry,field) if getattr(entry,field) is not None else '') for field in tracked_fields}
            changed={field:{'before':before[field],'after':after[field]} for field in tracked_fields if before[field]!=after[field]}
            AuditLog.objects.create(
                actor=request.user,
                action='finance_transaction_correction',
                path=request.path,
                method='POST',
                object_type='FinancialTransaction',
                object_id=str(entry.pk),
                summary=f'اصلاح کامل تراکنش مالی {entry.person_name}'[:250],
                metadata={'changes':changed,'review_status':'approved','note':note},
                ip_address=_request_ip(request),
            )
            if entry.recorded_by_id and entry.recorded_by_id!=request.user.pk:
                StaffNotification.objects.create(
                    user=entry.recorded_by,
                    title='اصلاح ثبت مالی',
                    message=f'اطلاعات تراکنش {entry.person_name} توسط مدیر اصلاح و تأیید شد.',
                    notification_type='finance_review',
                    related_date=timezone.localdate(),
                )
        messages.success(request,'اطلاعات تراکنش اصلاح و تأیید شد؛ مقادیر قبلی در سابقه حسابرسی محفوظ است.')
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
