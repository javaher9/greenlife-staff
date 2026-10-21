from datetime import datetime, time, timedelta

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone

from .device_booking_models import DeviceSessionBooking
from .models import AuditLog, Branch, VisitAppointment
from .sms import SmsGatewayError, send_sms
from intake.models import IntakeInvitation


_ALLOWED_ROLES={'call_center','receptionist','consultant','doctor','admin','manager','internal_manager'}


def _profile(request):
    profile=getattr(request.user,'profile',None)
    if not profile or not getattr(profile,'is_active',True):
        raise PermissionDenied('پروفایل پرسنلی فعال نیست.')
    if profile.role not in _ALLOWED_ROLES and not request.user.is_superuser:
        raise PermissionDenied('دسترسی به وضعیت زنده برای این نقش فعال نیست.')
    return profile


def _is_executive(user):
    return bool(
        getattr(user,'is_superuser',False)
        or (getattr(user,'username','') or '').lower() in getattr(settings,'EXECUTIVE_USERNAMES',())
    )


def _requested_branch(request,profile):
    raw=(request.GET.get('branch') or request.POST.get('branch') or '').strip()
    if raw.isdigit() and (
        request.user.is_superuser
        or profile.role in ('admin','manager','internal_manager')
        or (profile.role=='doctor' and _is_executive(request.user))
    ):
        return Branch.objects.filter(pk=int(raw),is_active=True).first()
    return getattr(profile,'branch',None)


def _local_slot(day,clock):
    return timezone.make_aware(datetime.combine(day,clock),timezone.get_current_timezone())


def _visit_state(item,now):
    if item.status=='cancelled':
        return 'cancelled','لغو شده',False
    if item.status=='no_show':
        return 'no_show','عدم مراجعه',True
    if item.status=='completed' or item.care_stage=='closed':
        return 'completed','تکمیل چرخه',False
    if item.status=='booked':
        passed=item.appointment_date==timezone.localdate() and _local_slot(item.appointment_date,item.appointment_time)<now-timedelta(minutes=15)
        if passed:
            return 'overdue','زمان مراجعه گذشته',True
        return 'booked','رزرو شده',False
    if item.status=='arrived' and item.care_stage=='doctor':
        invitation = getattr(item, 'intake_invitation', None)
        if invitation:
            if invitation.completed_at:
                return 'intake_completed','اطلاعات اولیه تکمیل شد · آماده آنالیز',False
            if invitation.started_at:
                return 'intake_started','در حال تکمیل فرم اطلاعات اولیه',False
            if invitation.sent_at:
                return 'intake_sent','لینک فرم ارسال شد · در انتظار تکمیل',False
        return 'arrived','پذیرش شد',False
    if item.care_stage=='consultant':
        return 'consultant','ویزیت پزشک انجام شد · نزد مشاور',False
    if item.care_stage=='payment':
        return 'payment','مشاوره انجام شد · در انتظار پرداخت',False
    return 'arrived','مراجعه کرده',False


def _device_state(item,now):
    if item.status=='completed':
        return 'completed','انجام شد',False
    if item.status=='arrived':
        return 'arrived','حاضر شد',False
    if item.status=='late':
        return 'late','دیر رسید',True
    if item.status=='no_show':
        return 'no_show','نیامد',True
    if item.status=='cancelled':
        return 'cancelled','لغو شده',False
    if item.status=='rescheduled':
        return 'rescheduled','جابجا شد',False
    if item.status=='booked' and item.starts_at<now-timedelta(minutes=10):
        return 'overdue','زمان نوبت گذشته',True
    return 'booked','رزرو شده',False


def _visit_queryset(request,profile,branch):
    today=timezone.localdate()
    if profile.role=='call_center':
        return (
            VisitAppointment.objects
            .filter(appointment_date__range=(today,today+timedelta(days=1)))
            .filter(Q(lead__assigned_to=profile) | Q(created_by=request.user,source='call_center'))
            .select_related('branch','lead','intake_invitation')
            .order_by('appointment_date','appointment_time','id')
            .distinct()
        )
    if not branch:
        return VisitAppointment.objects.none()
    return (
        VisitAppointment.objects
        .filter(branch=branch,appointment_date=today)
        .select_related('branch','lead')
        .order_by('appointment_time','id')
    )


def _can_access_appointment(request,profile,item):
    if profile.role=='call_center':
        return bool(
            (item.lead_id and item.lead and item.lead.assigned_to_id==profile.pk)
            or (item.created_by_id==request.user.id and item.source=='call_center')
        )
    branch=_requested_branch(request,profile)
    return bool(branch and item.branch_id==branch.pk)


@login_required
def staff_live_status_api(request):
    profile=_profile(request)
    branch=_requested_branch(request,profile)
    now=timezone.localtime()
    today=timezone.localdate()

    visits=[]
    for item in _visit_queryset(request,profile,branch)[:40]:
        key,label,needs_action=_visit_state(item,now)
        visits.append({
            'id':item.pk,
            'name':item.full_name,
            'phone':item.phone,
            'time':item.appointment_time.strftime('%H:%M'),
            'date':item.appointment_date.isoformat(),
            'day_label':'امروز' if item.appointment_date==today else 'فردا',
            'branch':item.branch.name,
            'service':item.service or 'ویزیت',
            'status_key':key,
            'status_label':label,
            'arrival_url':reverse('receptionist_appointment_status',args=[item.pk,'arrived']) if profile.role=='receptionist' and item.status=='booked' else '',
            'needs_action':needs_action,
            'patient_url':reverse('patient_360_from_appointment',args=[item.pk]),
        })

    devices=[]
    if profile.role!='call_center' and branch:
        qs=(
            DeviceSessionBooking.objects
            .filter(branch=branch,starts_at__date=today)
            .select_related('appointment','device','secondary_device','plan_item','branch')
            .order_by('starts_at','id')
        )
        for item in qs[:50]:
            key,label,needs_action=_device_state(item,now)
            device_name=item.device.name
            if item.secondary_device_id:
                device_name=f'{device_name} + {item.secondary_device.name}'
            service=item.plan_item.title if item.plan_item_id else ''
            if item.plan_item_id and getattr(item.plan_item,'area',''):
                service=f'{service} · {item.plan_item.area}'
            devices.append({
                'id':item.pk,
                'appointment_id':item.appointment_id,
                'name':item.appointment.full_name,
                'phone':item.appointment.phone,
                'time':timezone.localtime(item.starts_at).strftime('%H:%M'),
                'device':device_name,
                'service':service,
                'status_key':key,
                'status_label':label,
                'needs_action':needs_action,
                'patient_url':reverse('patient_360_from_appointment',args=[item.appointment_id]),
            })

    response=JsonResponse({
        'ok':True,
        'role':profile.role,
        'branch':branch.name if branch else '',
        'show_devices':profile.role!='call_center',
        'visits':visits,
        'devices':devices,
        'refreshed_at':now.strftime('%H:%M:%S'),
    },json_dumps_params={'ensure_ascii':False})
    response['Cache-Control']='no-store, private'
    return response


@login_required
def staff_live_quick_sms(request):
    if request.method!='POST':
        return JsonResponse({'ok':False,'error':'method not allowed'},status=405)
    profile=_profile(request)
    appointment_raw=(request.POST.get('appointment') or '').strip()
    device_raw=(request.POST.get('device_booking') or '').strip()

    item=None
    device_booking=None
    if device_raw.isdigit():
        device_booking=(
            DeviceSessionBooking.objects
            .select_related('appointment','appointment__lead','branch')
            .filter(pk=int(device_raw)).first()
        )
        item=device_booking.appointment if device_booking else None
    elif appointment_raw.isdigit():
        item=(
            VisitAppointment.objects
            .select_related('lead','branch')
            .filter(pk=int(appointment_raw)).first()
        )

    if not item or not _can_access_appointment(request,profile,item):
        return JsonResponse({'ok':False,'error':'نوبت برای شما قابل دسترسی نیست.'},status=403)

    body=(
        f'سلام {item.full_name}، برای پیگیری نوبت شما در گرین‌لایف {item.branch.name} '
        'با شما در تماس هستیم. لطفاً برای هماهنگی زمان مراجعه با ما تماس بگیرید.'
    )
    try:
        send_sms(
            item.phone,body,purpose='live_status_followup',
            created_by=request.user,appointment=item,
        )
    except SmsGatewayError as exc:
        return JsonResponse({'ok':False,'error':str(exc)},status=400)

    AuditLog.objects.create(
        actor=request.user,action='live_status_followup_sms',
        path=request.path,method='POST',
        object_type='DeviceSessionBooking' if device_booking else 'VisitAppointment',
        object_id=str(device_booking.pk if device_booking else item.pk),
        summary='Follow-up SMS sent from live status plaque',
        metadata={'appointment_id':item.pk,'phone':item.phone,'branch':item.branch.name},
    )
    return JsonResponse({'ok':True,'message':'SMS پیگیری ارسال شد.'},json_dumps_params={'ensure_ascii':False})
