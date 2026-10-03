from datetime import datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .jalali import format_jalali, parse_jalali
from .models import (
    ApiServerSettings, Branch, ConsultationPlan, ConsultationPlanItem,
    BranchDeviceTypeStatus, DeviceCabin, DeviceSessionBooking, DeviceTypeSchedule,
    FinancialTransaction, PhysicalDevice, VisitAppointment,
)
from .sms import send_sms


def _profile(request):
    profile=getattr(request.user,'profile',None)
    if not profile:
        raise PermissionDenied('پروفایل پرسنلی لازم است.')
    return profile


def _role_allowed(profile, roles):
    if profile.role not in roles:
        raise PermissionDenied('دسترسی این بخش برای شما فعال نیست.')


def _device_branches():
    """Only real treatment branches belong in device scheduling/settings."""
    return (
        Branch.objects.filter(is_active=True)
        .exclude(name__in=('افسریه','کال‌سنتر','کال سنتر','Call Center'))
        .order_by('name')
    )


def _branch_for_settings(request):
    profile=getattr(request.user,'profile',None)
    branch_id=(request.POST.get('branch') or request.GET.get('branch') or '').strip()
    allowed=_device_branches()

    if request.user.is_superuser:
        if branch_id.isdigit():
            return get_object_or_404(allowed,pk=int(branch_id))
        if profile and profile.branch_id:
            own=allowed.filter(pk=profile.branch_id).first()
            if own:
                return own
        branch=allowed.first()
        if not branch:
            raise PermissionDenied('شعبه درمانی فعالی برای دستگاه‌ها وجود ندارد.')
        return branch

    if not profile:
        raise PermissionDenied('پروفایل پرسنلی لازم است.')
    _role_allowed(profile,('admin','manager','internal_manager'))
    if profile.role=='admin' and branch_id.isdigit():
        return get_object_or_404(allowed,pk=int(branch_id))
    if not profile.branch_id:
        raise PermissionDenied('شعبه شما تعریف نشده است.')
    branch=allowed.filter(pk=profile.branch_id).first()
    if not branch:
        raise PermissionDenied('این مرکز برای نوبت‌دهی دستگاه تعریف نشده است.')
    return branch


def _mins(raw,default):
    try:
        value=int(raw)
    except (TypeError,ValueError):
        return default
    return max(0,min(240,value))


def _parse_time(value):
    return time.fromisoformat(value)


def _next_device_type_code():
    prefix='TYPE'
    used=set(DeviceTypeSchedule.objects.filter(code__startswith=prefix).values_list('code',flat=True))
    i=1
    while f'{prefix}{i}' in used:
        i+=1
    return f'{prefix}{i}'


def _send_confirmation(pk):
    try:
        booking=DeviceSessionBooking.objects.select_related(
            'appointment','branch','device','secondary_device'
        ).get(pk=pk)
        config=ApiServerSettings.load()
        if not (config.is_enabled and config.appointment_confirmation_enabled and config.is_configured):
            return
        label=booking.device.device_type.name
        if booking.secondary_device_id:
            label='Double Define'
        body=(
            f'گرین لایف\n{booking.appointment.full_name} عزیز، نوبت {label} شما '
            f'در {booking.branch.name}، {format_jalali(timezone.localtime(booking.starts_at).date())} '
            f'ساعت {timezone.localtime(booking.starts_at):%H:%M} ثبت شد.\n02134247'
        )
        send_sms(
            booking.appointment.phone,body,purpose='appointment',
            appointment=booking.appointment,created_by=booking.created_by,
        )
        DeviceSessionBooking.objects.filter(pk=pk,confirmation_sent_at__isnull=True).update(
            confirmation_sent_at=timezone.now()
        )
    except Exception:
        # SMS is best effort: never cancel a valid booked treatment.
        return


@login_required
def device_capacity_settings(request):
    branch=_branch_for_settings(request)
    if request.method=='POST':
        if not request.user.is_superuser:
            _role_allowed(_profile(request),('admin','manager'))
        action=request.POST.get('action')
        if action=='toggle_type_branch':
            kind=get_object_or_404(DeviceTypeSchedule,pk=request.POST.get('type_id'),is_active=True)
            target_active=(request.POST.get('active')=='1')
            if not target_active:
                has_future_booking=DeviceSessionBooking.objects.filter(
                    branch=branch,
                    status='booked',
                    starts_at__gte=timezone.now(),
                ).filter(
                    Q(device__device_type=kind)|Q(secondary_device__device_type=kind)
                ).exists()
                if has_future_booking:
                    messages.error(
                        request,
                        'این نوع دستگاه در این شعبه نوبت آینده فعال دارد؛ ابتدا نوبت‌های آینده آن را تعیین تکلیف کنید.'
                    )
                else:
                    status,_=BranchDeviceTypeStatus.objects.get_or_create(
                        branch=branch,device_type=kind,
                    )
                    status.is_active=False
                    status.save(update_fields=['is_active'])
                    messages.success(request,f'{kind.name} برای شعبه {branch.name} غیرفعال شد.')
            else:
                status,_=BranchDeviceTypeStatus.objects.get_or_create(
                    branch=branch,device_type=kind,
                )
                status.is_active=True
                status.save(update_fields=['is_active'])
                messages.success(request,f'{kind.name} برای شعبه {branch.name} فعال شد.')
        elif action=='new_type':
            name=(request.POST.get('name') or '').strip()[:100]
            treatment=_mins(request.POST.get('treatment_minutes'),60)
            preparation=_mins(request.POST.get('preparation_minutes'),20)
            if not name:
                messages.error(request,'نام دستگاه الزامی است.')
            elif treatment<10:
                messages.error(request,'مدت درمان باید حداقل ۱۰ دقیقه باشد.')
            else:
                code=_next_device_type_code()
                DeviceTypeSchedule.objects.create(
                    name=name,code=code,
                    treatment_minutes=treatment,
                    preparation_minutes=preparation,
                    is_active=True,
                )
                messages.success(request,f'{name} به بانک دستگاه‌ها اضافه شد.')
        elif action=='type':
            kind=get_object_or_404(DeviceTypeSchedule,pk=request.POST.get('type_id'))
            name=(request.POST.get('name') or '').strip()[:100]
            treatment=_mins(request.POST.get('treatment_minutes'),kind.treatment_minutes)
            preparation=_mins(request.POST.get('preparation_minutes'),kind.preparation_minutes)
            if not name:
                messages.error(request,'نام دستگاه الزامی است.')
            elif treatment<10:
                messages.error(request,'مدت درمان باید حداقل ۱۰ دقیقه باشد.')
            else:
                kind.name=name
                kind.treatment_minutes=treatment
                kind.preparation_minutes=preparation
                kind.save(update_fields=['name','treatment_minutes','preparation_minutes'])
                messages.success(request,'اطلاعات نوع دستگاه به‌روزرسانی شد؛ نوبت‌های ثبت‌شده قبلی بدون تغییر می‌مانند.')
        elif action=='delete_type':
            with transaction.atomic():
                kind=get_object_or_404(
                    DeviceTypeSchedule.objects.select_for_update(),
                    pk=request.POST.get('type_id'),
                )
                used_devices=PhysicalDevice.objects.filter(device_type=kind)
                if used_devices.exists():
                    messages.error(
                        request,
                        f'{kind.name} در یک یا چند مرکز به دستگاه فیزیکی متصل است؛ ابتدا آن دستگاه‌ها را حذف کنید یا در صورت داشتن سابقه غیرفعال نگه دارید.'
                    )
                else:
                    name=kind.name
                    kind.delete()
                    messages.success(request,f'{name} از بانک دستگاه‌ها حذف شد.')
        elif action=='cabin':
            name=(request.POST.get('name') or '').strip()[:100]
            if name:
                cabin,created=DeviceCabin.objects.get_or_create(branch=branch,name=name)
                messages.success(request,'کابین ثبت شد.' if created else 'این کابین قبلاً ثبت شده است.')
        elif action=='device':
            kind=get_object_or_404(DeviceTypeSchedule,pk=request.POST.get('type_id'))
            name=(request.POST.get('name') or '').strip()[:100]
            if name:
                with transaction.atomic():
                    device,created=PhysicalDevice.objects.get_or_create(
                        branch=branch,name=name,
                        defaults={'device_type':kind},
                    )
                    if created and not device.cabin_id:
                        internal_cabin,_=DeviceCabin.objects.get_or_create(
                            branch=branch,name=f'__DEV_{device.pk}',
                            defaults={'is_active':True},
                        )
                        device.cabin=internal_cabin
                        device.save(update_fields=['cabin'])
                messages.success(request,'دستگاه ثبت شد.' if created else 'این نام دستگاه قبلاً ثبت شده است.')
        elif action=='delete_device':
            with transaction.atomic():
                device=get_object_or_404(
                    PhysicalDevice.objects.select_for_update(),
                    pk=request.POST.get('device_id'),branch=branch,
                )
                has_history=DeviceSessionBooking.objects.filter(
                    Q(device=device)|Q(secondary_device=device)
                ).exists()
                if has_history:
                    messages.error(
                        request,
                        f'{device.name} سابقه نوبت دارد و برای حفظ تاریخچه قابل حذف نیست؛ آن را غیرفعال کنید.'
                    )
                else:
                    name=device.name
                    device.delete()
                    messages.success(request,f'{name} حذف شد.')
        elif action=='delete_cabin':
            with transaction.atomic():
                cabin=get_object_or_404(
                    DeviceCabin.objects.select_for_update(),
                    pk=request.POST.get('cabin_id'),branch=branch,
                )
                if cabin.assigned_devices.exists():
                    messages.error(
                        request,
                        f'کابین {cabin.name} هنوز دستگاه متصل دارد؛ ابتدا دستگاه‌ها را جابه‌جا یا حذف کنید.'
                    )
                elif cabin.device_sessions.exists():
                    messages.error(
                        request,
                        f'کابین {cabin.name} سابقه نوبت دارد و برای حفظ تاریخچه قابل حذف نیست.'
                    )
                else:
                    name=cabin.name
                    cabin.delete()
                    messages.success(request,f'کابین {name} حذف شد.')
        elif action=='toggle_device':
            device=get_object_or_404(PhysicalDevice,pk=request.POST.get('device_id'),branch=branch)
            target_active=(request.POST.get('active')=='1')
            if not target_active:
                has_future_booking=DeviceSessionBooking.objects.filter(
                    Q(device=device)|Q(secondary_device=device),
                    status='booked',starts_at__gte=timezone.now(),
                ).exists()
                if has_future_booking:
                    messages.error(
                        request,
                        'این دستگاه نوبت آینده فعال دارد؛ ابتدا نوبت‌های آینده آن را تعیین تکلیف کنید.'
                    )
                else:
                    device.is_active=False
                    device.save(update_fields=['is_active'])
                    messages.success(request,f'{device.name} غیرفعال شد و از نوبت‌دهی این شعبه خارج شد.')
            else:
                device.is_active=True
                device.save(update_fields=['is_active'])
                messages.success(request,f'{device.name} دوباره فعال شد و در نوبت‌دهی قابل استفاده است.')
        elif action=='move':
            device=get_object_or_404(PhysicalDevice,pk=request.POST.get('device_id'),branch=branch)
            try:
                start=_parse_time(request.POST.get('work_start') or '08:30')
                last=_parse_time(request.POST.get('last_start') or '17:30')
            except ValueError:
                messages.error(request,'ساعت کاری معتبر نیست.')
            else:
                if start>=last:
                    messages.error(request,'ساعت شروع باید قبل از آخرین شروع نوبت باشد.')
                else:
                    if not device.cabin_id:
                        internal_cabin,_=DeviceCabin.objects.get_or_create(
                            branch=branch,name=f'__DEV_{device.pk}',
                            defaults={'is_active':True},
                        )
                        device.cabin=internal_cabin
                    device.work_start=start
                    device.last_start=last
                    device.save(update_fields=['cabin','work_start','last_start'])
                    messages.success(request,'ساعت کاری دستگاه ذخیره شد.')
        return redirect(f'/settings/device-capacity/?branch={branch.pk}')

    types=list(DeviceTypeSchedule.objects.all())

    return render(request,'core/device_capacity_settings.html',{
        'branch':branch,'branches':_device_branches(),
        'is_admin':request.user.is_superuser or _profile(request).role=='admin',
        'types':types,'active_types':types,
        'devices':PhysicalDevice.objects.filter(branch=branch).select_related('device_type','cabin'),
    })


@login_required
def device_booking_schedule(request):
    profile=_profile(request)
    _role_allowed(profile,('consultant','receptionist','admin','manager','internal_manager'))
    branch_id=(request.POST.get('branch') or request.GET.get('branch') or '').strip()
    allowed_branches=_device_branches()
    if profile.role=='admin' and branch_id.isdigit():
        branch=get_object_or_404(allowed_branches,pk=int(branch_id))
    else:
        if not profile.branch_id:
            if profile.role=='admin':
                branch=allowed_branches.first()
                if not branch:
                    raise PermissionDenied('شعبه درمانی فعالی برای دستگاه‌ها وجود ندارد.')
            else:
                raise PermissionDenied('شعبه شما تعریف نشده است.')
        else:
            branch=allowed_branches.filter(pk=profile.branch_id).first()
            if not branch:
                raise PermissionDenied('این مرکز برای نوبت‌دهی دستگاه تعریف نشده است.')
    raw_day=(request.POST.get('day') or request.GET.get('day') or '').strip()
    try:
        day=parse_jalali(raw_day) if raw_day else timezone.localdate()
    except (ValueError,TypeError):
        day=timezone.localdate()
    selected_raw=(request.POST.get('appointment') or request.GET.get('appointment') or '').strip()
    appointment=(
        VisitAppointment.objects.filter(pk=int(selected_raw),branch=branch)
        .select_related('consultation_plan').first()
        if selected_raw.isdigit() else None
    )
    plan=getattr(appointment,'consultation_plan',None) if appointment else None

    if request.method=='POST':
        if profile.role not in ('consultant','admin','manager'):
            raise PermissionDenied('ثبت نوبت دستگاه فقط برای مشاور یا مدیریت فعال است.')
        if not appointment or not plan or plan.status not in (
            'finalized','payment_pending','partial_paid','paid'
        ):
            messages.error(request,'ابتدا پکیج بیمار را نهایی کنید.')
            return redirect('device_booking_schedule')
        with transaction.atomic():
            # A branch-wide DB lock serialises concurrent machine allocation even
            # if two consultants click at the same instant.
            Branch.objects.select_for_update().get(pk=branch.pk)
            item=get_object_or_404(
                ConsultationPlanItem,pk=request.POST.get('plan_item'),
                plan=plan,kind='device',included=True,
            )
            existing=item.device_sessions.exclude(status__in=('cancelled','rescheduled','no_show'))
            if existing.filter(status__in=('booked','arrived','late')).exists():
                messages.error(request,'برای این خدمت یک جلسه رزرو فعال وجود دارد؛ ابتدا آن را انجام یا لغو کنید.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}')
            if existing.count()>=item.quantity:
                messages.error(request,'تمام جلسات خریداری‌شده این خدمت قبلاً رزرو یا انجام شده‌اند.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}')
            paid=FinancialTransaction.objects.filter(
                appointment=appointment,source='manual',entry_type='inc',
                review_status__in=('pending','approved'),
            ).aggregate(total=Sum('amount'))['total'] or 0
            if paid<=0 and plan.status!='paid':
                messages.error(request,'برای رزرو قطعی، ابتدا بیعانه یا تسویه را ثبت کنید.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}')
            device=get_object_or_404(
                PhysicalDevice.objects.select_related('device_type','cabin'),
                pk=request.POST.get('device'),branch=branch,is_active=True,
            )
            if not device.cabin_id:
                internal_cabin,_=DeviceCabin.objects.get_or_create(
                    branch=branch,name=f'__DEV_{device.pk}',
                    defaults={'is_active':True},
                )
                device.cabin=internal_cabin
                device.save(update_fields=['cabin'])
            cabin=device.cabin
            second_raw=(request.POST.get('secondary_device') or '').strip()
            second=(
                get_object_or_404(PhysicalDevice.objects.select_related('device_type','cabin'),
                                  pk=int(second_raw),branch=branch,is_active=True)
                if second_raw.isdigit() else None
            )
            if second and (second.pk==device.pk or
                second.device_type.code!='DIF70' or device.device_type.code!='DIF70'):
                messages.error(request,'برای Double Define دو دستگاه مجزای DIF70 انتخاب کنید.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}')
            requested_type=(request.POST.get('double_define')=='1')
            if requested_type and not second:
                messages.error(request,'برای Double Define دستگاه دوم الزامی است.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}')
            if second and not requested_type:
                messages.error(request,'برای استفاده هم‌زمان، گزینه Double Define را انتخاب کنید.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}')
            try:
                start_clock=_parse_time(request.POST.get('start_time') or '')
                start=timezone.make_aware(datetime.combine(day,start_clock))
            except (ValueError,TypeError):
                messages.error(request,'ساعت نوبت معتبر نیست.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}')
            if start<=timezone.now():
                messages.error(request,'نوبت باید در آینده باشد.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}')
            machines=(device,second) if second else (device,)
            if any(start_clock<m.work_start or start_clock>m.last_start for m in machines):
                messages.error(request,'این ساعت خارج از بازه کاری دستگاه است.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}')
            for machine in machines:
                machine_slot_minutes=max(
                    10,
                    int(machine.device_type.treatment_minutes or 0)
                    + int(machine.device_type.preparation_minutes or 0),
                )
                candidate=timezone.make_aware(datetime.combine(day,machine.work_start))
                last_candidate=timezone.make_aware(datetime.combine(day,machine.last_start))
                valid_slot=False
                while candidate<=last_candidate:
                    if candidate==start:
                        valid_slot=True
                        break
                    candidate+=timedelta(minutes=machine_slot_minutes)
                if not valid_slot:
                    messages.error(request,'زمان انتخاب‌شده باید یکی از ردیف‌های استاندارد همین دستگاه باشد.')
                    return redirect(f'/device-bookings/?appointment={appointment.pk}&day={raw_day}')
            treatment=max(m.device_type.treatment_minutes for m in machines)
            preparation=max(m.device_type.preparation_minutes for m in machines)
            treatment_end=start+timedelta(minutes=treatment)
            end=treatment_end+timedelta(minutes=preparation)
            booked=DeviceSessionBooking.objects.filter(
                branch=branch,status__in=('booked','arrived','late','completed'),
                starts_at__lt=end,blocked_until__gt=start,
            )
            machine_ids={m.pk for m in machines}
            collision=booked.filter(
                Q(device_id__in=machine_ids) |
                Q(secondary_device_id__in=machine_ids) |
                Q(appointment=appointment),
            ).exists()
            if collision:
                messages.error(request,'در این بازه دستگاه یا خود بیمار رزرو هم‌پوشان دارد.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}&day={raw_day}')
            created=DeviceSessionBooking.objects.create(
                branch=branch,appointment=appointment,plan_item=item,
                cabin=cabin,device=device,secondary_device=second,
                starts_at=start,treatment_ends_at=treatment_end,blocked_until=end,
                treatment_minutes_snapshot=treatment,
                preparation_minutes_snapshot=preparation,
                created_by=request.user,
            )
            transaction.on_commit(lambda pk=created.pk:_send_confirmation(pk))
        messages.success(request,'نوبت تک‌جلسه‌ای ثبت شد؛ ظرفیت دستگاه تا پایان آماده‌سازی اشغال است.')
        return redirect(f'/device-bookings/?appointment={appointment.pk}&day={raw_day}')

    bookings=(
        DeviceSessionBooking.objects.filter(branch=branch,starts_at__date=day)
        .select_related('appointment','device','secondary_device','cabin','plan_item')
        .order_by('starts_at','device__name','id')
    )
    booking_list=list(bookings)
    blocking_statuses={'booked','arrived','late','completed'}
    history_statuses={'no_show','cancelled','rescheduled'}
    device_lines=list(
        PhysicalDevice.objects.filter(branch=branch,is_active=True)
        .select_related('device_type','cabin')
        .order_by('name','id')
    )
    device_cards=[]
    now=timezone.now()
    for device_line in device_lines:
        slot_minutes=max(
            10,
            int(device_line.device_type.treatment_minutes or 0)
            + int(device_line.device_type.preparation_minutes or 0),
        )
        work_start=timezone.make_aware(datetime.combine(day,device_line.work_start))
        last_start=timezone.make_aware(datetime.combine(day,device_line.last_start))
        cursor=work_start
        slot_number=1
        slots=[]
        free_count=0
        busy_count=0
        off_count=0
        while cursor<=last_start:
            slot_end=cursor+timedelta(minutes=slot_minutes)
            matches=[
                b for b in booking_list
                if (
                    b.device_id==device_line.pk
                    or b.secondary_device_id==device_line.pk
                )
                and b.starts_at<slot_end and b.blocked_until>cursor
            ]
            hit=next((b for b in matches if b.status in blocking_statuses),None)
            history_hit=next((b for b in reversed(matches) if b.status in history_statuses),None)
            if hit:
                state='busy'
                busy_count+=1
                busy_reason='device'
            elif history_hit:
                state='history'
                free_count+=1
                busy_reason=''
            elif day==timezone.localdate() and slot_end<=now:
                state='off'
                off_count+=1
                busy_reason=''
            else:
                state='free'
                free_count+=1
                busy_reason=''
            slots.append({
                'number':slot_number,
                'device':device_line,
                'state':state,
                'booking':hit,
                'history_booking':history_hit,
                'busy_reason':busy_reason,
                'start_value':cursor.strftime('%H:%M'),
                'start_label':cursor.strftime('%H:%M'),
                'end_label':slot_end.strftime('%H:%M'),
            })
            cursor=slot_end
            slot_number+=1
        device_cards.append({
            'device':device_line,
            'slots':slots,
            'slot_minutes':slot_minutes,
            'total_count':len(slots),
            'free_count':free_count,
            'busy_count':busy_count,
            'off_count':off_count,
        })

    # Patient picker: do not hide patients merely because their package is still
    # being finalized. The booking POST guard remains strict, but consultants
    # can always find/select the patient and see the package state.
    plans=(
        ConsultationPlan.objects.filter(appointment__branch=branch)
        .exclude(status='no_sale')
        .select_related('appointment')
        .order_by('-updated_at','-id')[:300]
    )
    bookable_plan_statuses=('finalized','payment_pending','partial_paid','paid')
    plan_ready=bool(plan and plan.status in bookable_plan_statuses)
    previous_day=day-timedelta(days=1)
    next_day=day+timedelta(days=1)
    return render(request,'core/device_booking_schedule.html',{
        'branch':branch,'day':day,'day_jalali':format_jalali(day),
        'previous_day_jalali':format_jalali(previous_day),
        'next_day_jalali':format_jalali(next_day),
        'today_jalali':format_jalali(timezone.localdate()),
        'appointment':appointment,'plan':plan,'plan_ready':plan_ready,
        'items':plan.items.filter(kind='device',included=True) if plan_ready else [],
        'plans':plans,'bookings':booking_list,
        'devices':device_lines,'device_lines':device_lines,
        'device_cards':device_cards,
        'can_book':profile.role in ('consultant','admin','manager'),
        'can_update_status':profile.role in ('consultant','receptionist','admin','manager'),
        'can_manage':profile.role in ('admin','manager','internal_manager'),
        'is_admin':profile.role=='admin',
        'branches':_device_branches(),
    })


@login_required
def device_booking_status(request,pk,status):
    if request.method!='POST':
        return redirect('device_booking_schedule')
    profile=_profile(request)
    _role_allowed(profile,('consultant','receptionist','admin','manager'))
    allowed={
        'booked':'رزرو عادی',
        'arrived':'حاضر شد',
        'late':'دیر رسید',
        'completed':'انجام شد',
        'no_show':'نیامد',
        'cancelled':'لغو شد',
        'rescheduled':'جابجا شد',
    }
    if status not in allowed:
        raise PermissionDenied('وضعیت نوبت معتبر نیست.')

    qs=DeviceSessionBooking.objects.select_for_update().select_related('appointment','branch')
    if not (request.user.is_superuser or profile.role=='admin'):
        if not profile.branch_id:
            raise PermissionDenied('شعبه شما مشخص نشده است.')
        qs=qs.filter(branch_id=profile.branch_id)

    with transaction.atomic():
        booking=get_object_or_404(qs,pk=pk)
        booking.status=status
        booking.save(update_fields=['status','updated_at'])

    day=format_jalali(timezone.localtime(booking.starts_at).date())
    if status=='rescheduled':
        messages.success(request,f'نوبت {booking.appointment.full_name} به‌عنوان جابجا شده ثبت شد؛ ردیف قبلی آزاد است و می‌توانید زمان جدید را انتخاب کنید.')
    else:
        messages.success(request,f'وضعیت {booking.appointment.full_name}: {allowed[status]}')
    return redirect(f'/device-bookings/?appointment={booking.appointment_id}&day={day}')


@login_required
def device_booking_cancel(request,pk):
    if request.method!='POST':
        return redirect('device_booking_schedule')
    profile=_profile(request)
    _role_allowed(profile,('consultant','admin','manager'))
    with transaction.atomic():
        booking=get_object_or_404(
            DeviceSessionBooking.objects.select_for_update().select_related('appointment'),
            pk=pk,branch_id=profile.branch_id,
        )
        if booking.status=='booked':
            booking.status='cancelled'
            booking.save(update_fields=['status','updated_at'])
            # Rescheduling never edits the original booking snapshot.
            messages.success(request,'نوبت لغو شد و ظرفیت برای رزرو تازه آزاد است.')
        else:
            messages.error(request,'فقط نوبت رزرو شده قابل لغو است.')
    return redirect(f'/device-bookings/?appointment={booking.appointment_id}')
