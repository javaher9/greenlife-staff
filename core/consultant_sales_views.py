from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .call_center_identity import call_center_display_name
from .models import (
    ConsultationPlan, ConsultationPlanItem, EmployeeProfile, FinancialTransaction,
    PatientProfile, ReferralLead, StaffNotification, Task, TreatmentCatalogItem,
    VisitAppointment, normalize_lead_phone,
)


def _consultant(request):
    profile=getattr(request.user,'profile',None)
    return profile if profile and profile.role=='consultant' and profile.branch_id else None


def _queue(profile):
    return (
        VisitAppointment.objects
        .filter(branch_id=profile.branch_id,care_stage='consultant')
        .exclude(status='cancelled')
        .select_related('lead','doctor_completed_by','branch')
        .prefetch_related('diet_programs','device_programs','lipolytic_programs','care_notes')
        .order_by('doctor_completed_at','appointment_time','id')
    )


def _catalog_price(branch,kind,name):
    qs=TreatmentCatalogItem.objects.filter(category=kind,name__iexact=(name or '').strip(),is_active=True)
    if branch:
        local=qs.filter(branch=branch).order_by('sort_order','id').first()
        if local and local.price_toman is not None:
            return local.price_toman
    global_item=qs.filter(branch__isnull=True).order_by('sort_order','id').first()
    return global_item.price_toman if global_item and global_item.price_toman is not None else Decimal('0')


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
        subtotal += (item.unit_price_toman or 0) * (item.quantity or 0)
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
            raw_price=(request.POST.get('unit_price_toman') or '').replace(',','').strip()
            try:
                item.unit_price_toman=max(Decimal('0'),Decimal(raw_price or '0'))
            except InvalidOperation:
                item.unit_price_toman=Decimal('0')
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
                quantity=qty,unit_price_toman=price,
                note=(request.POST.get('item_note') or '').strip()[:2000],
                sort_order=(plan.items.order_by('-sort_order').values_list('sort_order',flat=True).first() or 0)+10,
            )
            _recalculate(plan)
            messages.success(request,'خدمت جدید به پکیج مشاور اضافه شد.')
            return redirect(f"{reverse('consultant_sales_outcomes')}?appointment={selected.pk}")

        if action=='finalize':
            raw_discount=(request.POST.get('discount_toman') or '').replace(',','').strip()
            try:
                discount=max(Decimal('0'),Decimal(raw_discount or '0'))
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
            if plan.status not in ('finalized','payment_pending'):
                messages.error(request,'ابتدا پکیج را نهایی کنید.')
                return redirect(f"{reverse('consultant_sales_outcomes')}?appointment={selected.pk}")
            with transaction.atomic():
                plan.status='payment_pending'
                plan.sent_to_reception_at=timezone.now()
                plan.save(update_fields=['status','sent_to_reception_at','updated_at'])
                selected.care_stage='payment'
                selected.save(update_fields=['care_stage','updated_at'])
                receptionists=User.objects.filter(
                    is_active=True,profile__is_active=True,profile__role='receptionist',
                    profile__branch=selected.branch,
                )
                amount=f'{int(plan.final_amount_toman):,}'
                for user in receptionists:
                    StaffNotification.objects.create(
                        user=user,title='پرداخت جدید از مشاور',
                        message=f'{selected.full_name} · مبلغ نهایی {amount} تومان · آماده دریافت',
                        notification_type='consultant_payment',related_date=timezone.localdate(),
                    )
            messages.success(request,'پرونده برای منشی ارسال شد و در صف «در انتظار پرداخت» قرار گرفت.')
            return redirect('consultant_sales_outcomes')

        if action=='no_sale':
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

    pending=list(appointments[:80])
    recent_paid=FinancialTransaction.objects.filter(
        source='manual',recorded_by=request.user,entry_type='inc'
    ).exclude(review_status='cancelled').select_related('appointment').order_by('-created_at')[:12]

    doctor_notes=[]
    if selected:
        doctor_notes=list(selected.care_notes.filter(note_type='clinical')[:8])

    return render(request,'core/consultant_sales_outcomes.html',{
        'pending':pending,'selected':selected,'plan':plan,
        'plan_items':list(plan.items.all()) if plan else [],
        'doctor_notes':doctor_notes,'recent_paid':recent_paid,
        'item_kinds':ConsultationPlanItem.KIND,
        'failure_reasons':[
            ('financial','مشکل مالی'),('side_effects','نگرانی از عوارض'),
            ('more_review','نیاز به بررسی بیشتر'),('other','سایر'),
        ],
        'payment_url':(
            f"{reverse('finance_entry')}?appointment={selected.pk}"
            if selected and plan and plan.status in ('finalized','payment_pending') else ''
        ),
    })
