from datetime import date, datetime, timedelta

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
from .patient_ui import attach_patient_photos
from .call_center_identity import call_center_display_name
from .models import Branch, EmployeeProfile, ReferralLead, StaffNotification, Task, VisitAppointment, SmsAutomationRule, SmsScheduledMessage
from .sms_automation import schedule_sms_event, sms_staff_display_name
from .jalali import format_jalali
from .sms import send_appointment_confirmation


ALLOWED_APPOINTMENT_ROLES={'admin','internal_manager','manager','call_center','receptionist'}

def _queue_appointment_messages(appointment_id):
    """Honor configurable SMS rules without changing legacy booking delivery."""
    appointment=VisitAppointment.objects.select_related('branch','created_by','created_by__profile').get(pk=appointment_id)
    event_at=timezone.make_aware(
        datetime.combine(appointment.appointment_date,appointment.appointment_time),
        timezone.get_current_timezone(),
    )
    context={
        'name':appointment.full_name,
        'phone':appointment.phone,
        'branch':appointment.branch.name,
        'address':getattr(appointment.branch,'address','') or '',
        'service':appointment.service,
        'date':format_jalali(appointment.appointment_date),
        'time':appointment.appointment_time.strftime('%H:%M'),
        'staff':sms_staff_display_name(appointment.created_by),
        'event':'نوبت',
    }
    # Preserve existing appointment confirmation while the new rule is only
    # being configured. The custom rule takes over only when explicitly enabled.
    if SmsAutomationRule.objects.filter(event='appointment_booked',is_enabled=True).exists():
        schedule_sms_event(
            'appointment_booked',appointment.pk,event_at=event_at,
            patient_number=appointment.phone,context=context,
        )
    else:
        send_appointment_confirmation(appointment_id)
    schedule_sms_event(
        'appointment_reminder',appointment.pk,event_at=event_at,
        patient_number=appointment.phone,context=context,
    )



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


def _next_open_appointment_day(day, direction=1):
    """Move Friday to the nearest enabled clinic day."""
    step=1 if direction >= 0 else -1
    while day.weekday()==4:
        day += timedelta(days=step)
    return day


def _shift_open_appointment_days(day, count):
    """Shift by clinic days while Fridays stay out of the appointment calendar."""
    if not count:
        return _next_open_appointment_day(day)
    step=1 if count > 0 else -1
    current=_next_open_appointment_day(day, step)
    moved=0
    while moved < abs(count):
        current += timedelta(days=step)
        if current.weekday()!=4:
            moved += 1
    return current


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
    if day.weekday()==4:
        return JsonResponse({
            'ok':True,'branch':branch.pk,'date':day.isoformat(),
            'closed':True,'slots':[],
        })
    booked=set(
        VisitAppointment.objects.filter(
            branch=branch,appointment_date=day
        ).exclude(status__in=('cancelled','no_show')).values_list('appointment_time',flat=True)
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
    start=_next_open_appointment_day(_parse_requested_date(request.GET.get('date')))
    branches=_clinic_branches()
    profile=getattr(request.user,'profile',None)

    if role=='receptionist':
        branch=getattr(profile,'branch',None)
        if not branch:
            raise PermissionDenied('برای منشی شعبه مشخص نشده است.')
    else:
        branch_id=(request.GET.get('branch') or '').strip()
        branch=branches.filter(pk=int(branch_id)).first() if branch_id.isdigit() else branches.first()

    # Seven visible clinic days; Fridays are deliberately not rendered.
    display_days=[]
    cursor=start
    while len(display_days)<7:
        if cursor.weekday()!=4:
            display_days.append(cursor)
        cursor += timedelta(days=1)

    appointments=[]
    if branch:
        appointments=attach_patient_photos(list(
            VisitAppointment.objects.filter(
                branch=branch,appointment_date__in=display_days
            ).exclude(status__in=('cancelled','no_show')).select_related(
                'lead','created_by','created_by__profile'
            ).order_by('appointment_date','appointment_time')
        ))

    for item in appointments:
        creator=item.created_by
        item.booking_by_label=''
        item.booking_by_prefix='ثبت'
        item.booking_created_time=timezone.localtime(item.created_at).strftime('%H:%M')
        if creator:
            creator_role=getattr(getattr(creator,'profile',None),'role','')
            if creator_role=='call_center':
                item.booking_by_label=call_center_display_name(creator)
                item.booking_by_prefix='گل'
            else:
                item.booking_by_label=creator.get_full_name() or creator.username

    by_day_time={
        (item.appointment_date,item.appointment_time.strftime('%H:%M')):item
        for item in appointments
    }
    weekday_names=('دوشنبه','سه‌شنبه','چهارشنبه','پنجشنبه','جمعه','شنبه','یکشنبه')
    schedule_days=[]
    for day in display_days:
        rows=[
            {'time':value,'appointment':by_day_time.get((day,value))}
            for value,_label in visit_appointment_time_choices()
        ]
        schedule_days.append({
            'date':day,
            'date_iso':day.isoformat(),
            'jalali':format_jalali(day,persian_digits=False),
            'weekday':weekday_names[day.weekday()],
            'is_today':day==timezone.localdate(),
            'rows':rows,
            'booked_count':sum(1 for row in rows if row['appointment']),
        })

    prev_start=_shift_open_appointment_days(start,-7)
    next_start=_shift_open_appointment_days(start,7)
    return render(request,'core/appointments/schedule.html',{
        'appointment_role':role,
        'schedule_date':start,
        'schedule_start_jalali':format_jalali(start,persian_digits=False),
        'schedule_branch':branch,
        'appointment_branches':branches,
        'schedule_days':schedule_days,
        'schedule_prev':prev_start,
        'schedule_next':next_start,
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
                if lead.status!='appointment' or lead.contact_result!='appointment':
                    lead.status='appointment'
                    lead.contact_result='appointment'
                    lead.next_follow_up=None
                    lead.save(update_fields=['status','contact_result','next_follow_up','updated_at'])
                _notify_branch_receptionists(appointment)
                transaction.on_commit(
                    lambda appointment_id=appointment.pk: _queue_appointment_messages(appointment_id)
                )
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
                transaction.on_commit(
                    lambda appointment_id=item.pk: _queue_appointment_messages(appointment_id)
                )
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
    if status not in ('arrived','completed','no_show','cancelled'):
        raise PermissionDenied('وضعیت نامعتبر است.')
    item=get_object_or_404(
        VisitAppointment,
        pk=pk,
        branch=request.user.profile.branch,
    )
    with transaction.atomic():
        item.status=status
        item.save(update_fields=['status','updated_at'])
        if status in ('cancelled','no_show'):
            SmsScheduledMessage.objects.filter(
                event_key__in=[
                    f'appointment_booked:{item.pk}:patient',
                    f'appointment_reminder:{item.pk}:patient',
                    f'appointment_booked:{item.pk}:executive',
                    f'appointment_reminder:{item.pk}:executive',
                    f'appointment_booked:{item.pk}:internal_manager',
                    f'appointment_reminder:{item.pk}:internal_manager',
                    f'appointment_booked:{item.pk}:staff',
                    f'appointment_reminder:{item.pk}:staff',
                    f'appointment_booked:{item.pk}:custom',
                    f'appointment_reminder:{item.pk}:custom',
                ],status='pending',
            ).update(status='cancelled')
        if status=='no_show' and item.lead_id:
            lead=ReferralLead.objects.select_related('assigned_to__user','first_appointment_by').get(pk=item.lead_id)
            follow_up_day=timezone.localdate()+timedelta(days=1)
            if lead.status!='won':
                lead.status='contacted'
                lead.contact_result='follow_up'
                lead.next_follow_up=follow_up_day
                lead.notes=((lead.notes or '')+f'\n[{timezone.localdate()}] عدم مراجعه به نوبت؛ پیگیری مجدد لازم است.').strip()
                lead.save(update_fields=['status','contact_result','next_follow_up','notes','updated_at'])
            operator=lead.first_appointment_by or (lead.assigned_to.user if lead.assigned_to_id else None)
            if operator:
                Task.objects.get_or_create(
                    title=f'پیگیری عدم مراجعه: {item.full_name}',
                    assigned_to=operator,
                    due_date=follow_up_day,
                    defaults={
                        'description':f'بیمار در نوبت {item.appointment_date} ساعت {item.appointment_time:%H:%M} مراجعه نکرد.\nتلفن: {item.phone}',
                        'created_by':request.user,
                        'priority':'high',
                        'status':'todo',
                    },
                )
                StaffNotification.objects.create(
                    user=operator,
                    title='عدم مراجعه بیمار',
                    message=f'{item.full_name} مراجعه نکرد؛ پیگیری برای فردا ثبت شد.',
                    notification_type='lead_follow_up',
                    related_date=follow_up_day,
                )
        # Close the operational loop back to call center. Arrival/completion means
        # the lead has actually visited, but never downgrade a won/lost lead.
        if item.lead_id and status in ('arrived','completed'):
            ReferralLead.objects.filter(pk=item.lead_id).exclude(
                status__in=('won','lost')
            ).update(status='visited',updated_at=timezone.now())
    messages.success(request,f'وضعیت نوبت {item.full_name} به «{item.get_status_display()}» تغییر کرد.')
    if request.POST.get('next')=='dashboard':
        return redirect('dashboard')
    return redirect(f"{reverse('appointment_schedule')}?date={item.appointment_date.isoformat()}")
