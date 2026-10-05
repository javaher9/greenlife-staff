from datetime import datetime, time

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from .models import (
    Attendance, ConsultationPlan, FinancialTransaction, MeetingActionItem,
    ReferralLead, Task, VisitAppointment,
)
from .device_booking_models import DeviceSessionBooking
from .jalali import format_jalali
from .sms_automation import schedule_sms_event


def _aware(day, clock=time(9,0)):
    return timezone.make_aware(datetime.combine(day,clock),timezone.get_current_timezone())


def _appointment_context(a, event):
    return {
        'name':a.full_name,'phone':a.phone,'branch':a.branch.name,
        'address':getattr(a.branch,'address','') or '',
        'service':a.service,'date':format_jalali(a.appointment_date),
        'time':a.appointment_time.strftime('%H:%M'),'event':event,
        'notes':a.notes,
    }


@receiver(pre_save,sender=VisitAppointment)
def remember_appointment_sms_state(sender,instance,**kwargs):
    if not instance.pk:
        instance._sms_previous=None
        return
    instance._sms_previous=VisitAppointment.objects.filter(pk=instance.pk).values(
        'appointment_date','appointment_time','status'
    ).first()


@receiver(post_save,sender=VisitAppointment)
def appointment_sms_events(sender,instance,created,**kwargs):
    if created:
        return  # booking/reminder are already queued by the existing appointment workflow
    previous=getattr(instance,'_sms_previous',None) or {}
    if previous and (previous.get('appointment_date'),previous.get('appointment_time')) != (instance.appointment_date,instance.appointment_time):
        event_at=_aware(instance.appointment_date,instance.appointment_time)
        schedule_sms_event('appointment_changed',f'{instance.pk}-{instance.updated_at:%Y%m%d%H%M%S%f}',
            event_at=event_at,patient_number=instance.phone,
            context=_appointment_context(instance,'تغییر نوبت'))
    mapping={'arrived':'patient_arrived','cancelled':'appointment_cancelled'}
    event=mapping.get(instance.status)
    if event and previous.get('status')!=instance.status:
        schedule_sms_event(event,f'{instance.pk}-{instance.status}',patient_number=instance.phone,
            context=_appointment_context(instance,instance.get_status_display()))


@receiver(post_save,sender=DeviceSessionBooking)
def device_session_sms_events(sender,instance,created,**kwargs):
    a=instance.appointment
    context=_appointment_context(a,'جلسه دستگاه')
    context['service']=getattr(instance.device,'name','') or a.service
    context['date']=format_jalali(timezone.localtime(instance.starts_at).date())
    context['time']=timezone.localtime(instance.starts_at).strftime('%H:%M')
    if created:
        schedule_sms_event('device_session_booked',instance.pk,event_at=instance.starts_at,patient_number=a.phone,context=context)
        schedule_sms_event('device_session_reminder',instance.pk,event_at=instance.starts_at,patient_number=a.phone,context=context)
        return
    if instance.status in ('arrived','late'):
        schedule_sms_event('device_session_started',f'{instance.pk}-started',patient_number=a.phone,context=context)
    elif instance.status=='completed':
        schedule_sms_event('device_session_finished',f'{instance.pk}-finished',patient_number=a.phone,context=context)
        schedule_sms_event('treatment_followup',f'{instance.pk}-followup',event_at=timezone.now(),patient_number=a.phone,context=context)


@receiver(post_save,sender=ConsultationPlan)
def payment_due_sms(sender,instance,created,**kwargs):
    if instance.status not in ('payment_pending','partial_paid'):
        return
    a=instance.appointment
    context=_appointment_context(a,'یادآوری پرداخت')
    context['amount']=str(instance.final_amount_toman or 0)
    schedule_sms_event('payment_due',f'{instance.pk}-{instance.status}',patient_number=a.phone,context=context)


@receiver(post_save,sender=FinancialTransaction)
def payment_approved_sms(sender,instance,created,**kwargs):
    if instance.entry_type!='inc' or instance.review_status!='approved' or not instance.appointment_id:
        return
    a=instance.appointment
    context=_appointment_context(a,'تأیید پرداخت')
    context['amount']=str(instance.amount or 0)
    schedule_sms_event('payment_approved',instance.pk,patient_number=a.phone,context=context)


@receiver(post_save,sender=ReferralLead)
def lead_new_sms(sender,instance,created,**kwargs):
    if not created:
        return
    schedule_sms_event('lead_new',instance.pk,patient_number=instance.phone,
        staff_number=getattr(instance.assigned_to,'phone','') if instance.assigned_to_id else '',
        context={'name':instance.full_name,'phone':instance.phone,'service':instance.interested_service,
                 'notes':instance.notes,'event':'لید جدید'})


@receiver(post_save,sender=Attendance)
def staff_late_sms(sender,instance,created,**kwargs):
    if instance.status!='late':
        return
    profile=getattr(instance.user,'profile',None)
    schedule_sms_event('staff_late',f'{instance.pk}-{instance.date}',staff_number=getattr(profile,'phone',''),
        context={'name':instance.user.get_full_name() or instance.user.username,'staff':instance.user.get_full_name(),
                 'branch':instance.branch.name if instance.branch else '','date':str(instance.date),
                 'time':timezone.localtime(instance.check_in).strftime('%H:%M') if instance.check_in else '',
                 'event':'تأخیر حضور','notes':instance.note})


@receiver(post_save,sender=Task)
def staff_task_due_sms(sender,instance,created,**kwargs):
    if not instance.due_date or instance.status=='done':
        return
    profile=getattr(instance.assigned_to,'profile',None)
    schedule_sms_event('staff_task_due',instance.pk,event_at=_aware(instance.due_date),
        staff_number=getattr(profile,'phone',''),
        context={'name':instance.assigned_to.get_full_name() or instance.assigned_to.username,
                 'staff':instance.assigned_to.get_full_name(),'date':str(instance.due_date),
                 'event':'سررسید وظیفه','notes':instance.title})


@receiver(post_save,sender=MeetingActionItem)
def internal_approval_sms(sender,instance,created,**kwargs):
    if instance.status!='done' or not instance.approved_at:
        return
    profile=getattr(instance.assigned_to,'profile',None)
    schedule_sms_event('internal_approval',instance.pk,staff_number=getattr(profile,'phone',''),
        context={'name':instance.assigned_to.get_full_name() or instance.assigned_to.username,
                 'staff':instance.assigned_to.get_full_name(),'event':'تأیید مدیریتی','notes':instance.title})
