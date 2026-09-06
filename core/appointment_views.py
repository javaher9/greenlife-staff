from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import AppointmentFromLeadForm, ReceptionistAppointmentForm, visit_appointment_time_choices
from .jalali import parse_jalali
from .models import Branch, EmployeeProfile, ReferralLead, StaffNotification, VisitAppointment


ALLOWED_APPOINTMENT_ROLES={'admin','internal_manager','manager','call_center','receptionist'}


def _role(user):
    return getattr(getattr(user,'profile',None),'role','employee')


def _clinic_branches():
    return Branch.objects.filter(is_active=True).exclude(name__in=('کال‌سنتر','کال سنتر','Call Center')).order_by('name')


def _appointment_access_required(view):
    @login_required
    def wrapper(request,*args,**kwargs):
        if _role(request.user) not in ALLOWED_APPOINTMENT_ROLES:
            raise PermissionDenied('دسترسی نوبت‌دهی برای این نقش فعال نیست.')
        return view(request,*args,**kwargs)
    return wrapper


def _parse_requested_date(raw):
    raw=(raw or '').strip()
    if not raw:
        return timezone.localdate()
    try:
        if '-' in raw:
            return date.fromisoformat(raw)
        return parse_jalali(raw)
    except Exception:
        return timezone.localdate()


def _notify_branch_receptionists(appointment):
    recipients=EmployeeProfile.objects.filter(
        role='receptionist',
        branch=appointment.branch,
        is_active=True,
        user__is_active=True,
    ).select_related('user')
    for profile in recipients:
        StaffNotification.objects.create(
            user=profile.user,
            title='نوبت جدید ثبت شد',
            message=(
                f'{appointment.full_name} برای {appointment.appointment_date:%Y-%m-%d} '
                f'ساعت {appointment.appointment_time:%H:%M} نوبت دارد.'
            ),
            notification_type='appointment',
            related_date=appointment.appointment_date,
        )


@_appointment_access_required
def appointment_availability(request):
    branch_id=(request.GET.get('branch') or '').strip()
    raw_date=(request.GET.get('date') or '').strip()
    if not branch_id.isdigit() or not raw_date:
        return JsonResponse({'ok':False,'error':'branch and date are required'},status=400)

    branch=get_object_or_404(_clinic_branches(),pk=int(branch_id))
    if _role(request.user)=='receptionist' and getattr(request.user.profile,'branch_id',None)!=branch.pk:
        raise PermissionDenied('منشی فقط به نوبت‌های شعبه خودش دسترسی دارد.')
    day=_parse_requested_date(raw_date)
    booked=set(
        VisitAppointment.objects.filter(
            branch=branch,appointment_date=day
        ).exclude(status='cancelled').values_list('appointment_time',flat=True)
    )
    slots=[]
    for value,label in visit_appointment_time_choices():
        hour,minute=(int(x) for x in value.split(':'))
        occupied=any(x.hour==hour and x.minute==minute for x in booked)
        slots.append({'value':value,'label':label,'available':not occupied})
    return JsonResponse({
        'ok':True,
        'branch':branch.pk,
        'date':day.isoformat(),
        'slots':slots,
    })


@_appointment_access_required
def appointment_schedule(request):
    role=_role(request.user)
    day=_parse_requested_date(request.GET.get('date'))
    branches=_clinic_branches()
    profile=getattr(request.user,'profile',None)

    if role=='receptionist':
        branch=getattr(profile,'branch',None)
        if not branch:
            raise PermissionDenied('برای منشی شعبه مشخص نشده است.')
    else:
        branch_id=(request.GET.get('branch') or '').strip()
        branch=branches.filter(pk=int(branch_id)).first() if branch_id.isdigit() else branches.first()

    appointments=[]
    if branch:
        appointments=list(
            VisitAppointment.objects.filter(
                branch=branch,appointment_date=day
            ).exclude(status='cancelled').select_related('lead','created_by').order_by('appointment_time')
        )
    by_time={a.appointment_time.strftime('%H:%M'):a for a in appointments}
    schedule_rows=[
        {'time':value,'appointment':by_time.get(value)}
        for value,_label in visit_appointment_time_choices()
    ]

    return render(request,'core/appointments/schedule.html',{
        'appointment_role':role,
        'schedule_date':day,
        'schedule_branch':branch,
        'appointment_branches':branches,
        'schedule_rows':schedule_rows,
    })


@login_required
def call_center_appointment_create(request,pk):
    if _role(request.user)!='call_center':
        raise PermissionDenied('این بخش فقط برای کال‌سنتر است.')

    lead=get_object_or_404(
        ReferralLead.objects.select_related('assigned_to','referrer__user'),
        pk=pk,
        assigned_to=request.user.profile,
    )
    initial={'appointment_date':timezone.localdate()}
    form=AppointmentFromLeadForm(request.POST or None,initial=initial)

    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        try:
            with transaction.atomic():
                appointment=VisitAppointment(
                    lead=lead,
                    branch=d['branch'],
                    full_name=lead.full_name,
                    phone=lead.phone,
                    service=lead.interested_service,
                    appointment_date=d['appointment_date'],
                    appointment_time=d['appointment_time'],
                    notes=d.get('notes') or '',
                    source='call_center',
                    created_by=request.user,
                )
                appointment.save()
                if lead.status!='appointment':
                    lead.status='appointment'
                    lead.save(update_fields=['status','updated_at'])
                _notify_branch_receptionists(appointment)
        except (IntegrityError,ValidationError):
            form.add_error('appointment_time','این ساعت همین الان رزرو شده است؛ یک ساعت دیگر انتخاب کنید.')
        else:
            messages.success(
                request,
                f'نوبت واقعی {lead.full_name} در شعبه {appointment.branch} '
                f'ساعت {appointment.appointment_time:%H:%M} ثبت شد و برای منشی قابل مشاهده است.'
            )
            return redirect('call_center_lead',pk=lead.pk)

    return render(request,'core/appointments/form.html',{
        'form':form,
        'lead':lead,
        'booking_source':'call_center',
        'title':'ثبت نوبت واقعی',
        'subtitle':f'{lead.full_name} · {lead.phone}',
    })


@login_required
def receptionist_appointment_create(request):
    if _role(request.user)!='receptionist':
        raise PermissionDenied('این بخش فقط برای منشی است.')
    branch=getattr(request.user.profile,'branch',None)
    if not branch:
        raise PermissionDenied('برای منشی شعبه مشخص نشده است.')

    form=ReceptionistAppointmentForm(
        request.POST or None,
        branch=branch,
        initial={'appointment_date':timezone.localdate()},
    )
    if request.method=='POST' and form.is_valid():
        item=form.save(commit=False)
        item.branch=branch
        item.source='receptionist'
        item.created_by=request.user
        try:
            with transaction.atomic():
                item.save()
        except (IntegrityError,ValidationError):
            form.add_error('appointment_time','این ساعت همین الان رزرو شده است؛ یک ساعت دیگر انتخاب کنید.')
        else:
            messages.success(
                request,
                f'نوبت {item.full_name} ساعت {item.appointment_time:%H:%M} ثبت شد.'
            )
            return redirect(f"{reverse('appointment_schedule')}?date={item.appointment_date.isoformat()}")

    return render(request,'core/appointments/form.html',{
        'form':form,
        'booking_source':'receptionist',
        'fixed_branch':branch,
        'title':'ثبت نوبت جدید',
        'subtitle':str(branch),
    })


@login_required
def receptionist_appointment_status(request,pk,status):
    if _role(request.user)!='receptionist' or request.method!='POST':
        raise PermissionDenied('این اقدام فقط برای منشی است.')
    if status not in ('arrived','completed','cancelled'):
        raise PermissionDenied('وضعیت نامعتبر است.')
    item=get_object_or_404(
        VisitAppointment,
        pk=pk,
        branch=request.user.profile.branch,
    )
    item.status=status
    item.save(update_fields=['status','updated_at'])
    messages.success(request,f'وضعیت نوبت {item.full_name} به «{item.get_status_display()}» تغییر کرد.')
    return redirect(f"{reverse('appointment_schedule')}?date={item.appointment_date.isoformat()}")
