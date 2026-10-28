"""Independent 50/50 skincare remittances, synchronized with the existing
approved finance ledger (never a parallel revenue total).

Amounts entered here are Green Life's share in toman. FinancialTransaction
stores the same amount in rial; approval in the standard finance workspace
is the sole step that includes it in the general revenue total.
"""
import uuid
from datetime import datetime, time, timedelta
from decimal import Decimal

from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import JalaliDateField
from .jalali import format_jalali
from .models import AuditLog, EmployeeProfile, FinancialTransaction, SkinCareSettlement


SKIN_CARE_PAYMENT_METHODS = [
    ('Pos S','POS-S'),
    ('CC G','CC-G'),
    ('Pos H','POS-H'),
    ('CC P','CC-P'),
    ('CC D','CC-D'),
    ('CC S','CC-S'),
    ('LINK','لینک پرداخت'),
    ('Bank Transfer','حواله / انتقال به حساب'),
    ('Cash','نقدی (نیازمند تأیید واریز)'),
]


class SkinCareSettlementForm(forms.Form):
    service_date=JalaliDateField(label='تاریخ خدمات',initial=timezone.localdate)
    company_share_toman=forms.DecimalField(
        label='مبلغ سهم گرین‌لایف (تومان)',
        min_value=1,max_digits=16,decimal_places=0,
        widget=forms.NumberInput(attrs={'step':'1','min':'1','inputmode':'numeric','placeholder':'مثلاً 30000000'}),
    )
    payment_method=forms.ChoiceField(label='مسیر واریز سهم گرین‌لایف',choices=SKIN_CARE_PAYMENT_METHODS)
    tracking_number=forms.CharField(label='شماره پیگیری واریز',required=False,max_length=100)
    receipt_image=forms.ImageField(
        label='تصویر رسید واریز',required=False,
        widget=forms.ClearableFileInput(attrs={'accept':'image/jpeg,image/png,image/webp'}),
    )
    description=forms.CharField(
        label='شرح خدمات (اختیاری)',required=False,max_length=300,
        widget=forms.Textarea(attrs={'rows':2,'placeholder':'مثلاً فیشیال یا پاکسازی پوست'}),
    )
    performer=forms.ModelChoiceField(
        label='کارشناس اسکین‌کر',
        queryset=EmployeeProfile.objects.none(),empty_label=None,
        widget=forms.Select(),
    )

    def __init__(self,*args,allowed_performers=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['performer'].queryset=allowed_performers or EmployeeProfile.objects.none()
        if self.fields['performer'].queryset.count()==1:
            self.fields['performer'].initial=self.fields['performer'].queryset.first().pk

    def clean_service_date(self):
        d=self.cleaned_data['service_date']
        if d > timezone.localdate():
            raise forms.ValidationError('تاریخ خدمات نمی‌تواند در آینده باشد.')
        return d

    def clean_receipt_image(self):
        image=self.cleaned_data.get('receipt_image')
        if image and image.size>10*1024*1024:
            raise forms.ValidationError('تصویر رسید باید کمتر از ۱۰ مگابایت باشد.')
        return image

    def clean(self):
        data=super().clean()
        method=data.get('payment_method')
        if method!='Cash' and not data.get('receipt_image'):
            self.add_error('receipt_image','برای دریافت غیرنقدی تصویر واریز سهم گرین‌لایف الزامی است.')
        if method=='Cash' and not data.get('description'):
            self.add_error('description','برای وجه نقد، توضیح محل نگهداری یا تحویل وجه الزامی است.')
        ref=(data.get('tracking_number') or '').strip()
        if ref and method:
            if SkinCareSettlement.objects.filter(
                payment_method=method,tracking_number=ref,
            ).exclude(finance_transaction__review_status='cancelled').exists():
                self.add_error('tracking_number','شماره پیگیری این واریز اسکین‌کر قبلاً ثبت شده است.')
        return data


def _allowed_performers(request):
    profile=getattr(request.user,'profile',None)
    role=getattr(profile,'role','')
    if not profile or not profile.is_active:
        raise PermissionDenied('حساب پرسنلی فعال لازم است.')
    if role in ('admin','internal_manager') or request.user.is_superuser:
        return EmployeeProfile.objects.filter(
            can_record_skin_care=True,is_active=True,user__is_active=True,
        ).select_related('user','branch').order_by('user__last_name','user__first_name')
    if role in ('manager','receptionist','consultant') and profile.branch_id:
        return EmployeeProfile.objects.filter(
            can_record_skin_care=True,is_active=True,user__is_active=True,branch_id=profile.branch_id,
        ).select_related('user','branch').order_by('user__last_name','user__first_name')
    if profile.can_record_skin_care:
        return EmployeeProfile.objects.filter(pk=profile.pk).select_related('user','branch')
    raise PermissionDenied('ثبت اسکین‌کر فقط برای مشاور، منشی، مسئول مجاز و مدیریت فعال است.')


@login_required
@require_http_methods(['GET','POST'])
def skin_care_home(request):
    allowed=_allowed_performers(request)
    profile=request.user.profile
    role=profile.role
    is_manager=request.user.is_superuser or role in ('admin','manager','internal_manager')
    allowed_ids=list(allowed.values_list('pk',flat=True))
    if not allowed_ids:
        # Do not fabricate a staff identity, branch or financial attribution.
        return render(request,'core/skin_care.html',{
            'unconfigured':True,'is_manager':is_manager,
            'entries':[],'form':None,
        })

    token=(request.POST.get('submission_token') or '').strip() if request.method=='POST' else uuid.uuid4().hex
    try:
        safe_token=uuid.UUID(token).hex
    except (ValueError,TypeError,AttributeError):
        safe_token=uuid.uuid4().hex
    finance_id='skin_care:'+safe_token
    if request.method=='POST' and FinancialTransaction.objects.filter(source='manual',external_id=finance_id).exists():
        messages.info(request,'این واریز قبلاً ثبت شده است؛ دوباره ثبت نشد.')
        return redirect('skin_care_home')

    form=SkinCareSettlementForm(
        request.POST or None,request.FILES or None,
        allowed_performers=allowed,
        initial={'service_date':timezone.localdate()},
    )
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        performer=d['performer']
        if performer.pk not in allowed_ids or not performer.branch_id:
            raise PermissionDenied('کارشناس مجاز باید به یک شعبه متصل باشد.')
        share=d['company_share_toman']
        if share > Decimal('999999999999999'):
            form.add_error('company_share_toman','مبلغ بیشتر از سقف مجاز است.')
        else:
            occurred_at=timezone.now()
            try:
                with transaction.atomic():
                    obj=FinancialTransaction.objects.create(
                        source='manual',external_id=finance_id,
                        branch=performer.branch,occurred_at=occurred_at,
                        amount=share*Decimal('10'),entry_type='inc',
                        payment_method=d['payment_method'],
                        sale_reason='skin_care',sale_origin='branch_walk_in',
                        service='اسکین‌کر',person_name=performer.user.get_full_name() or performer.user.username,
                        patient_ref='اسکین‌کر | تسویه همکاری',
                        account_heading='سهم گرین‌لایف از اسکین‌کر',
                        terminal_or_payee=d['payment_method'],
                        tracking_number=d['tracking_number'],
                        description=d['description'] or 'سهم ۵۰ درصدی گرین‌لایف از خدمات اسکین‌کر',
                        receipt_image=d.get('receipt_image'),
                        review_status='pending',
                        analysis_status='pending' if d.get('receipt_image') else 'skipped',
                        recorded_by=request.user,
                        raw_data={
                            'entry_channel':'skin_care_50_50',
                            'share_percent':'50',
                            'company_share_toman':str(share),
                            'gross_equivalent_toman':str(share*2),
                            'performer_profile_id':performer.pk,
                            'service_date':d['service_date'].isoformat(),
                            'submission_token':safe_token,
                        },
                    )
                    settlement=SkinCareSettlement.objects.create(
                        performer=performer,branch=performer.branch,
                        service_date=d['service_date'],
                        company_share_toman=share,
                        gross_equivalent_toman=share*2,
                        payment_method=d['payment_method'],
                        tracking_number=d['tracking_number'],
                        receipt_image=obj.receipt_image.name if obj.receipt_image else None,
                        description=d['description'],
                        created_by=request.user,
                        finance_transaction=obj,
                    )
                    AuditLog.objects.create(
                        actor=request.user,action='skin_care_entry',
                        path=request.path,method='POST',
                        object_type='SkinCareSettlement',object_id=str(settlement.pk),
                        summary='ثبت سهم اسکین‌کر، در انتظار تأیید مالی',
                        metadata={
                            'share_toman':str(share),'gross_toman':str(share*2),
                            'method':d['payment_method'],'performer_id':performer.pk,
                            'finance_id':obj.pk,'service_date':d['service_date'].isoformat(),
                        },
                    )
            except IntegrityError:
                messages.info(request,'شماره یا درخواست تکراری است؛ واریزی دوباره ثبت نشد.')
            else:
                messages.success(
                    request,f'سهم {int(share):,} تومان گرین‌لایف ثبت شد و در انتظار تأیید واریز است. کد پیگیری داخلی: {settlement.pk}'
                )
                return redirect('skin_care_home')

    entries=SkinCareSettlement.objects.filter(
        performer_id__in=allowed_ids,
    ).select_related('performer__user','branch','finance_transaction','created_by')
    if role not in ('admin','internal_manager') and not request.user.is_superuser and profile.branch_id:
        entries=entries.filter(branch_id=profile.branch_id)
    entries=entries[:60]
    today=timezone.localdate()
    start=timezone.make_aware(datetime.combine(today,time.min))
    end=start+timedelta(days=1)
    base=FinancialTransaction.objects.filter(
        entry_type='inc',sale_reason='skin_care',
        skin_care_settlement__performer_id__in=allowed_ids,
    )
    if role not in ('admin','internal_manager') and not request.user.is_superuser and profile.branch_id:
        base=base.filter(branch_id=profile.branch_id)
    confirmed=base.filter(review_status='approved',occurred_at__gte=start,occurred_at__lt=end)
    pending=base.filter(review_status='pending')
    return render(request,'core/skin_care.html',{
        'form':form,'entries':entries,'is_manager':is_manager,
        'submission_token':safe_token,
        'today_confirmed_rial':confirmed.aggregate(n=Sum('amount'))['n'] or 0,
        'pending_rial':pending.aggregate(n=Sum('amount'))['n'] or 0,
    })
