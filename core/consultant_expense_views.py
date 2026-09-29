"""Consultant-only petty expense entry; finance approval remains mandatory."""
from decimal import Decimal
from uuid import uuid4

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone

from .models import AuditLog, FinancialTransaction

COST_TYPES = (
    ('device', 'دستگاه و تجهیزات'),
    ('lipolytic', 'لیپولیتیک و مزوتراپی'),
    ('skin', 'پوست و زیبایی'),
    ('daya', 'دایا'),
    ('consumables', 'مواد مصرفی'),
    ('other', 'سایر'),
)


class ConsultantExpenseForm(forms.Form):
    amount_toman = forms.IntegerField(
        label='مبلغ هزینه (تومان)', min_value=1,
        widget=forms.NumberInput(attrs={'min': 1, 'step': 1, 'inputmode': 'numeric', 'placeholder': 'مبلغ به تومان'}),
    )
    category = forms.ChoiceField(label='دسته هزینه', choices=COST_TYPES)
    description = forms.CharField(
        label='شرح هزینه', max_length=1000,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'چه چیزی، برای چه کاری و از کجا تهیه شد؟'}),
    )
    receipt_image = forms.ImageField(
        label='تصویر رسید', required=True,
        widget=forms.ClearableFileInput(attrs={'accept': 'image/jpeg,image/png,image/webp'}),
    )

    def clean_receipt_image(self):
        receipt = self.cleaned_data['receipt_image']
        if receipt.size > 10 * 1024 * 1024:
            raise forms.ValidationError('حجم رسید باید کمتر از ۱۰ مگابایت باشد.')
        if receipt.content_type not in ('image/jpeg', 'image/png', 'image/webp'):
            raise forms.ValidationError('رسید باید JPG، PNG یا WebP باشد.')
        return receipt


@login_required
def consultant_expense_entry(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'consultant' or not profile.is_active or not profile.branch_id:
        raise PermissionDenied('ثبت هزینه مشاور فقط برای مشاور فعال دارای شعبه مجاز است.')

    form = ConsultantExpenseForm(request.POST or None, request.FILES or None)
    if request.method == 'POST' and form.is_valid():
        cleaned = form.cleaned_data
        category_label = dict(COST_TYPES)[cleaned['category']]
        image = cleaned['receipt_image']
        with transaction.atomic():
            entry = FinancialTransaction.objects.create(
                source='manual',
                external_id='consultant-expense-' + uuid4().hex,
                branch_id=profile.branch_id,
                occurred_at=timezone.now(),
                amount=Decimal(cleaned['amount_toman']) * Decimal('10'),
                entry_type='exp',
                account_heading=category_label,
                service=category_label,
                description=cleaned['description'].strip(),
                receipt_image=image,
                receipt_original_size=image.size,
                review_status='pending',
                analysis_status='pending',
                recorded_by=request.user,
                raw_data={
                    'entry_channel': 'consultant_expense',
                    'category': cleaned['category'],
                    'amount_unit': 'rial',
                    'entered_amount_toman': cleaned['amount_toman'],
                },
            )
            AuditLog.objects.create(
                actor=request.user,
                action='consultant_expense_entry',
                path=request.path[:255],
                method='POST',
                object_type='FinancialTransaction',
                object_id=str(entry.pk),
                summary=f'ثبت هزینه مشاور: {category_label}',
                metadata={'amount_rial': str(entry.amount), 'branch_id': profile.branch_id},
            )
        messages.success(request, 'هزینه همراه رسید ثبت شد و برای تأیید مالی در انتظار بررسی است.')
        return redirect('consultant_expense_entry')

    recent = list(FinancialTransaction.objects.filter(
        source='manual', entry_type='exp', recorded_by=request.user,
    ).order_by('-created_at')[:12])
    for entry in recent:
        entry.amount_toman_display = int(entry.amount / Decimal('10'))
    return render(request, 'core/consultant_expense_entry.html', {
        'form': form, 'recent_expenses': recent, 'branch': profile.branch,
    })
