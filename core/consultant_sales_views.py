from datetime import timedelta
from decimal import Decimal, InvalidOperation

# Consultant workspace deployment marker: force a clean application image build.

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .call_center_identity import call_center_display_name
from .patient_ui import attach_patient_photos, patient_photo_url_for_phone
from .device_pricing import device_unit_price
from .sales_target_models import SalesTargetBand, TargetPercentPolicy
from .jalali import gregorian_to_jalali, jalali_to_gregorian
from datetime import datetime, time
from .models import (
    ConsultationPlan, ConsultationPlanItem, DeviceBaseTariff, DeviceSessionBooking, EmployeeProfile, FinancialTransaction,
    PatientProfile, ReferralLead, StaffNotification, Task, TreatmentCatalogItem,
    VisitAppointment, normalize_lead_phone,
)



def _consultant_branch_target(profile):
    """Only the authenticated consultant's branch; no client-selected branch."""
    today=timezone.localdate()
    jy,jm,_=gregorian_to_jalali(today.year,today.month,today.day)
    start=datetime(*jalali_to_gregorian(jy,jm,1)).date()
    ny,nm=(jy+1,1) if jm==12 else (jy,jm+1)
    end=datetime(*jalali_to_gregorian(ny,nm,1)).date()
    saved=SalesTargetBand.objects.filter(key=f'{jy}-{jm:02d}:branch:{profile.branch_id}',scope='branch',branch_id=profile.branch_id).first()
    if not saved:
        return {'configured':False,'branch':profile.branch.name}
    policy=TargetPercentPolicy.objects.filter(period_year=jy,period_month=jm).first()
    if policy is None:
        policy=TargetPercentPolicy(period_year=jy,period_month=jm)
    heavy,floor,one,two=policy.bands(saved.sales_floor)
    base=FinancialTransaction.objects.filter(
        branch_id=profile.branch_id,source='manual',entry_type='inc',
        review_status='approved',occurred_at__gte=timezone.make_aware(datetime.combine(start,time.min)),
        occurred_at__lt=timezone.make_aware(datetime.combine(end,time.min)),
    )
    monthly=Decimal(base.aggregate(total=Sum('amount'))['total'] or 0)/Decimal('10000000')
    daily=Decimal(base.filter(occurred_at__date=today).aggregate(total=Sum('amount'))['total'] or 0)/Decimal('10000000')
    days=Decimal((end-start).days)
    def gauge(amount, divisor):
        # Use the same five target levels as the executive dashboard.
        # The daily thresholds are indicative; no penalty is finalized daily.
        thresholds=[x/divisor for x in (heavy,floor,one,two)]
        if amount<thresholds[0]: status,color='جریمه سنگین','red'
        elif amount<thresholds[1]: status,color='جریمه سبک','yellow'
        elif amount<thresholds[2]: status,color='کف فروش','green'
        elif amount<thresholds[3]: status,color='تارگت ۱','blue'
        else: status,color='تارگت ۲','purple'
        return {'percent':min(999,int(amount*100/thresholds[3])) if thresholds[3]>0 else 0,
                'status':status,'color':color}
    # Relative thresholds only: no financial amount is sent to the consultant HTML.
    # ASCII decimal strings: Django's Persian locale must not turn gauge data
    # into localized decimals that JavaScript Number() cannot parse.
    # This is percentage-only: raw sales amounts never leave this view.
    bands={
        'heavy':format(heavy*Decimal('100')/two,'.8f'),
        'floor':format(floor*Decimal('100')/two,'.8f'),
        'one':format(one*Decimal('100')/two,'.8f'),
        'two':'100',
    }
    return {'configured':True,'branch':profile.branch.name,'bands':bands,
            'daily':gauge(daily,days),'monthly':gauge(monthly,Decimal('1'))}



def _personal_consultant_performance(profile):
    """Current Jalali-month consultation funnel, scoped to THIS consultant and branch.

    Count actual consultation outcomes, not drafts, appointments belonging to
    colleagues, or all branch receipts. A sale means a fully paid plan.
    """
    from .models import ConsultationPlan

    today = timezone.localdate()
    jy, jm, _ = gregorian_to_jalali(today.year, today.month, today.day)
    start = datetime(*jalali_to_gregorian(jy, jm, 1)).date()
    ny, nm = (jy + 1, 1) if jm == 12 else (jy, jm + 1)
    end = datetime(*jalali_to_gregorian(ny, nm, 1)).date()

    plans = ConsultationPlan.objects.filter(
        consultant_id=profile.user_id,
        appointment__branch_id=profile.branch_id,
        appointment__appointment_date__gte=start,
        appointment__appointment_date__lt=end,
    ).exclude(appointment__status__in=('cancelled', 'no_show'))

    # Merely opening a consultation page creates a draft; it is NOT a
    # completed consultation. Only recorded outcomes count in the denominator.
    outcome_states = ('no_sale', 'finalized', 'payment_pending', 'partial_paid', 'paid')
    consultations = plans.filter(status__in=outcome_states).count()
    proposals = plans.filter(
        Q(finalized_at__isnull=False) |
        Q(status__in=('finalized', 'payment_pending', 'partial_paid', 'paid'))
    ).count()
    sales = plans.filter(status='paid').count()

    rate = round(sales * 100 / consultations) if consultations else None
    scale = consultations or 1
    return {
        'consultations': consultations,
        'proposals': proposals,
        'sales': sales,
        'conversion': rate,
        'consultations_width': 100 if consultations else 0,
        'proposals_width': round(proposals * 100 / scale),
        'sales_width': round(sales * 100 / scale),
        'has_data': bool(consultations),
    }



def _consultant(request):
    profile=getattr(request.user,'profile',None)
    return profile if profile and profile.role=='consultant' and profile.branch_id else None


def _queue(profile):
    return (
        VisitAppointment.objects
        .filter(branch_id=profile.branch_id)
        .filter(Q(care_stage__in=('consultant','payment')) | Q(consultation_plan__status='paid'))
        .exclude(status='cancelled')
        .select_related('lead','doctor_completed_by','branch')
        .prefetch_related('diet_programs','device_programs','lipolytic_programs','care_notes')
        .order_by('doctor_completed_at','appointment_time','id')
    )


def _catalog_price(branch,kind,name):
    if kind=='device':
        return device_unit_price(name,branch)
    qs=TreatmentCatalogItem.objects.filter(category=kind,name__iexact=(name or '').strip(),is_active=True)
    if branch:
        local=qs.filter(branch=branch).order_by('sort_order','id').first()
        if local and local.price_toman is not None:
            return local.price_toman
    global_item=qs.filter(branch__isnull=True).order_by('sort_order','id').first()
    if global_item and global_item.price_toman is not None:
        return global_item.price_toman
    return DeviceBaseTariff.current() if kind=='device' else Decimal('0')


def _doctor_name(program):
    user=getattr(program,'prescribed_by',None)
    if not user:
        return ''
    return user.get_full_name() or user.username


def _ensure_plan(appointment,consultant):
    plan,created=ConsultationPlan.objects.get_or_create(
        appointment=appointment,
        defaults={'consultant':consultant},
    )
    if not plan.consultant_id:
        plan.consultant=consultant
        plan.save(update_fields=['consultant','updated_at'])
    if not created or plan.items.exists():
        return plan

    rows=[]
    order=10
    for item in appointment.diet_programs.all():
        rows.append(ConsultationPlanItem(
            plan=plan,kind='diet',source='doctor',source_pk=item.pk,
            title=item.diet_name,area='',quantity=1,
            unit_price_toman=_catalog_price(appointment.branch,'diet',item.diet_name),
            note=item.note or '',sort_order=order,
            doctor_snapshot={
                'title':item.diet_name,'area':'','quantity':1,
                'recommendation_pack':item.recommendation_pack,
                'print_template':item.print_template,'note':item.note,
                'doctor':_doctor_name(item),
            },
        )); order+=10
    for item in appointment.device_programs.all():
        qty=max(1,item.sessions_prescribed or 1)
        rows.append(ConsultationPlanItem(
            plan=plan,kind='device',source='doctor',source_pk=item.pk,
            title=item.device_name,area=item.area or '',quantity=qty,
            unit_price_toman=_catalog_price(appointment.branch,'device',item.device_name),
            note=item.note or '',sort_order=order,
            doctor_snapshot={
                'title':item.device_name,'area':item.area,'quantity':qty,
                'note':item.note,'doctor':_doctor_name(item),
            },
        )); order+=10
    for item in appointment.lipolytic_programs.all():
        qty=max(1,item.sessions_prescribed or 1)
        rows.append(ConsultationPlanItem(
            plan=plan,kind='lipolytic',source='doctor',source_pk=item.pk,
            title=item.protocol_name,area=item.area or '',quantity=qty,
            unit_price_toman=_catalog_price(appointment.branch,'lipolytic',item.protocol_name),
            note=item.note or '',sort_order=order,
            doctor_snapshot={
                'title':item.protocol_name,'area':item.area,'quantity':qty,
                'note':item.note,'doctor':_doctor_name(item),
            },
        )); order+=10
    if rows:
        ConsultationPlanItem.objects.bulk_create(rows)
    _recalculate(plan)
    return plan


def _recalculate(plan,discount=None):
    subtotal=Decimal('0')
    for item in plan.items.filter(included=True):
        subtotal += (item.unit_price_toman or 0) * (item.quantity or 0) * (item.units_per_session or 1)
    if discount is None:
        discount=plan.discount_toman or Decimal('0')
    discount=max(Decimal('0'),min(Decimal(discount),subtotal))
    plan.subtotal_toman=subtotal
    plan.discount_toman=discount
    plan.final_amount_toman=max(Decimal('0'),subtotal-discount)
    plan.save(update_fields=['subtotal_toman','discount_toman','final_amount_toman','updated_at'])
    return plan


def _operator_user(lead):
    if not lead:
        return None
    if lead.first_appointment_by_id:
        return lead.first_appointment_by
    if lead.assigned_to_id:
        return lead.assigned_to.user
    return None


def _service_summary(plan):
    parts=[]
    for item in plan.items.filter(included=True).order_by('sort_order','id'):
        text=f'{item.title}'
        if item.area:
            text+=f' - {item.area}'
        if item.quantity:
            text+=f' × {item.quantity}'
        parts.append(text)
    return ' | '.join(parts)[:1500]


@login_required
def consultant_sales_outcomes(request):
    profile=_consultant(request)
    if not profile:
        messages.error(request,'این بخش فقط برای مشاور فعال است.')
        return redirect('dashboard')

    appointments=_queue(profile)
    selected_id=(request.POST.get('appointment_id') if request.method=='POST' else request.GET.get('appointment')) or ''
    selected=appointments.filter(pk=int(selected_id)).first() if str(selected_id).isdigit() else appointments.first()
    plan=_ensure_plan(selected,request.user) if selected else None

    if request.method=='POST':
        if not selected or not plan:
            messages.error(request,'پرونده انتخاب‌شده در صف مشاوره شما نیست.')
            return redirect('consultant_sales_outcomes')
        action=(request.POST.get('action') or '').strip()

        if action=='update_item':
            item=get_object_or_404(plan.items,pk=request.POST.get('item_id'))
            item.title=(request.POST.get('title') or item.title).strip()[:180]
            item.area=(request.POST.get('area') or '').strip()[:140]
            try:
                item.quantity=max(1,min(99,int(request.POST.get('quantity') or 1)))
            except (TypeError,ValueError):
                item.quantity=1
            raw_price=(request.POST.get('unit_price_million') or '').replace(',','').strip()
            try:
                item.unit_price_toman=max(Decimal('0'),Decimal(raw_price or '0') * Decimal('1000000'))
            except InvalidOperation:
                item.unit_price_toman=Decimal('0')
            try:
                item.units_per_session=max(1,min(12,int(request.POST.get('units_per_session') or 1)))
            except (TypeError,ValueError):
                item.units_per_session=1
            item.included=request.POST.get('included')=='1'
            item.note=(request.POST.get('item_note') or '').strip()[:2000]
            item.save()
            _recalculate(plan)
            messages.success(request,'پکیج نهایی به‌روزرسانی شد؛ نسخه پزشک دست‌نخورده باقی ماند.')
            return redirect(f"{reverse('consultant_sales_outcomes')}?appointment={selected.pk}")

        if action=='add_item':
            kind=(request.POST.get('kind') or 'other').strip()
            if kind not in dict(ConsultationPlanItem.KIND):
                kind='other'
            title=(request.POST.get('title') or '').strip()
            if not title:
                messages.error(request,'نام خدمت جدید را وارد کنید.')
                return redirect(f"{reverse('consultant_sales_outcomes')}?appointment={selected.pk}")
            try:
                qty=max(1,min(99,int(request.POST.get('quantity') or 1)))
            except (TypeError,ValueError):
                qty=1
            raw_price=(request.POST.get('unit_price_toman') or '').replace(',','').strip()
            try:
                price=max(Decimal('0'),Decimal(raw_price or '0'))
            except InvalidOperation:
                price=Decimal('0')
            ConsultationPlanItem.objects.create(
                plan=plan,kind=kind,source='consultant',title=title[:180],
                area=(request.POST.get('area') or '').strip()[:140],
                quantity=qty,units_per_session=max(1,min(12,int(request.POST.get('units_per_session') or 1))) if str(request.POST.get('units_per_session') or '1').isdigit() else 1,unit_price_toman=price,
                note=(request.POST.get('item_note') or '').strip()[:2000],
                sort_order=(plan.items.order_by('-sort_order').values_list('sort_order',flat=True).first() or 0)+10,
            )
            _recalculate(plan)
            messages.success(request,'خدمت جدید به پکیج مشاور اضافه شد.')
            return redirect(f"{reverse('consultant_sales_outcomes')}?appointment={selected.pk}")

        if action=='finalize':
            raw_discount=(request.POST.get('discount_million') or '').replace(',','').strip()
            try:
                discount=max(Decimal('0'),Decimal(raw_discount or '0') * Decimal('1000000'))
            except InvalidOperation:
                discount=Decimal('0')
            plan.note=(request.POST.get('plan_note') or '').strip()[:3000]
            _recalculate(plan,discount)
            if not plan.items.filter(included=True).exists():
                messages.error(request,'حداقل یک خدمت باید در پکیج نهایی باقی بماند.')
                return redirect(f"{reverse('consultant_sales_outcomes')}?appointment={selected.pk}")
            plan.status='finalized'
            plan.finalized_at=timezone.now()
            plan.consultant=request.user
            plan.save(update_fields=['status','finalized_at','consultant','note','updated_at'])
            messages.success(request,'پکیج نهایی شد. حالا پرداخت را خودتان ثبت کنید یا برای منشی بفرستید.')
            return redirect(f"{reverse('consultant_sales_outcomes')}?appointment={selected.pk}")

        if action=='send_to_reception':
            if plan.status not in ('finalized','payment_pending','partial_paid'):
                messages.error(request,'ابتدا پکیج را نهایی کنید.')
                return redirect(f"{reverse('consultant_sales_outcomes')}?appointment={selected.pk}")
            with transaction.atomic():
                if plan.status!='partial_paid':
                    plan.status='payment_pending'
                plan.sent_to_reception_at=timezone.now()
                plan.save(update_fields=['status','sent_to_reception_at','updated_at'])
                selected.care_stage='payment'
                selected.save(update_fields=['care_stage','updated_at'])
                receptionists=User.objects.filter(
                    is_active=True,profile__is_active=True,profile__role='receptionist',
                    profile__branch=selected.branch,
                )
                amount=format(plan.final_amount_toman / Decimal('1000000'),'f').rstrip('0').rstrip('.')
                for user in receptionists:
                    StaffNotification.objects.create(
                        user=user,title='پرداخت جدید از مشاور',
                        message=f'{selected.full_name} · مبلغ نهایی {amount} میلیون تومان · آماده دریافت',
                        notification_type='consultant_payment',related_date=timezone.localdate(),
                    )
            messages.success(request,'پرونده برای منشی ارسال شد و در صف «در انتظار پرداخت» قرار گرفت.')
            return redirect('consultant_sales_outcomes')

        if action=='no_sale':
            if plan.status in ('partial_paid','paid'):
                messages.error(request,'پس از دریافت وجه، وضعیت خرید نکرد ثبت نمی‌شود؛ اصلاح مالی را پیگیری کنید.')
                return redirect(f"{reverse('consultant_sales_outcomes')}?appointment={selected.pk}")
            reason=(request.POST.get('failure_reason') or 'more_review').strip()
            reason_labels={
                'financial':'مشکل مالی','side_effects':'نگرانی از عوارض',
                'more_review':'نیاز به بررسی بیشتر','other':'سایر',
            }
            if reason not in reason_labels:
                reason='other'
            note=(request.POST.get('failure_note') or '').strip()
            detail=f"فعلاً خرید نکرد - {reason_labels[reason]}"
            if note:
                detail+=f' | {note}'
            operator=_operator_user(selected.lead)
            tomorrow=timezone.localdate()+timedelta(days=1)
            with transaction.atomic():
                plan.status='no_sale'
                plan.note=((plan.note or '')+'\n'+detail).strip()
                plan.save(update_fields=['status','note','updated_at'])
                selected.care_stage='closed'
                selected.status='completed'
                selected.save(update_fields=['care_stage','status','updated_at'])
                if selected.lead_id:
                    selected.lead.status='contacted'
                    selected.lead.next_follow_up=tomorrow
                    selected.lead.notes=((selected.lead.notes or '')+f'\n[{timezone.localdate()}] {detail}').strip()
                    selected.lead.save(update_fields=['status','next_follow_up','notes','updated_at'])
                if operator:
                    Task.objects.create(
                        title=f'پیگیری پس از مشاوره: {selected.full_name}',
                        description=f'{detail}\nتلفن: {selected.phone}',
                        assigned_to=operator,created_by=request.user,due_date=tomorrow,
                        priority='high',status='todo',
                    )
                    StaffNotification.objects.create(
                        user=operator,title='پیگیری بیمار پس از مشاوره',
                        message=f'{selected.full_name} · {reason_labels[reason]} · {selected.phone}',
                        notification_type='lead_follow_up',related_date=tomorrow,
                    )
            messages.success(request,'نتیجه ثبت شد و پیگیری بعدی به کال‌سنتر برگشت.')
            return redirect('consultant_sales_outcomes')

        messages.error(request,'اقدام انتخاب‌شده معتبر نیست.')
        return redirect(f"{reverse('consultant_sales_outcomes')}?appointment={selected.pk}")

    pending=attach_patient_photos(list(appointments[:80]))
    if selected:
        attach_patient_photos([selected])
    recent_paid=FinancialTransaction.objects.filter(
        source='manual',recorded_by=request.user,entry_type='inc'
    ).exclude(review_status='cancelled').select_related('appointment').order_by('-created_at')[:12]

    today=timezone.localdate()
    kpis={
        'appointments_today':appointments.filter(appointment_date=today).count(),
        'awaiting_consultation':appointments.filter(care_stage='consultant').count(),
        'awaiting_payment':appointments.filter(care_stage='payment').count(),
        'finalized_today':appointments.filter(
            consultation_plan__status='paid',
            consultation_plan__updated_at__date=today,
        ).count(),
        'device_bookings_today':DeviceSessionBooking.objects.filter(
            branch_id=profile.branch_id,
            starts_at__date=today,
            status__in=('booked','completed'),
        ).count(),
        'expenses_pending':FinancialTransaction.objects.filter(
            source='manual',
            entry_type='exp',
            recorded_by=request.user,
            review_status='pending',
        ).count(),
    }

    doctor_notes=[]
    if selected:
        doctor_notes=list(selected.care_notes.filter(note_type='clinical')[:8])

    return render(request,'core/consultant_sales_outcomes.html',{
        'pending':pending,'selected':selected,'plan':plan,
        'plan_items':list(plan.items.all()) if plan else [],
        'doctor_notes':doctor_notes,'recent_paid':recent_paid,'kpis':kpis,
        'branch_target':_consultant_branch_target(profile),
        'personal_performance':_personal_consultant_performance(profile),
        'item_kinds':ConsultationPlanItem.KIND,
        'failure_reasons':[
            ('financial','مشکل مالی'),('side_effects','نگرانی از عوارض'),
            ('more_review','نیاز به بررسی بیشتر'),('other','سایر'),
        ],
        'payment_url':(
            f"{reverse('finance_entry')}?appointment={selected.pk}"
            if selected and plan and plan.status in ('finalized','payment_pending','partial_paid') else ''
        ),
    })
