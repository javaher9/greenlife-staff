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
    DeviceCabin, DeviceSessionBooking, DeviceTypeSchedule, FinancialTransaction,
    PhysicalDevice, VisitAppointment,
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


def _branch_for_settings(request):
    profile=_profile(request)
    _role_allowed(profile,('admin','manager','internal_manager'))
    branch_id=(request.POST.get('branch') or request.GET.get('branch') or '').strip()
    if profile.role=='admin' and branch_id.isdigit():
        return get_object_or_404(Branch,pk=int(branch_id))
    if not profile.branch_id:
        raise PermissionDenied('شعبه شما تعریف نشده است.')
    return profile.branch


def _mins(raw,default):
    try:
        value=int(raw)
    except (TypeError,ValueError):
        return default
    return max(0,min(240,value))


def _parse_time(value):
    return time.fromisoformat(value)


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
        _role_allowed(_profile(request),('admin','manager'))
        action=request.POST.get('action')
        if action=='type':
            kind=get_object_or_404(DeviceTypeSchedule,pk=request.POST.get('type_id'))
            treatment=_mins(request.POST.get('treatment_minutes'),kind.treatment_minutes)
            preparation=_mins(request.POST.get('preparation_minutes'),kind.preparation_minutes)
            if treatment<10:
                messages.error(request,'مدت درمان باید حداقل ۱۰ دقیقه باشد.')
            else:
                kind.treatment_minutes=treatment
                kind.preparation_minutes=preparation
                kind.save(update_fields=['treatment_minutes','preparation_minutes'])
                messages.success(request,'مدت دستگاه به‌روزرسانی شد؛ زمان نوبت‌های ثبت‌شده ثابت می‌ماند.')
        elif action=='cabin':
            name=(request.POST.get('name') or '').strip()[:100]
            if name:
                cabin,created=DeviceCabin.objects.get_or_create(branch=branch,name=name)
                messages.success(request,'کابین ثبت شد.' if created else 'این کابین قبلاً ثبت شده است.')
        elif action=='device':
            kind=get_object_or_404(DeviceTypeSchedule,pk=request.POST.get('type_id'))
            cabin=get_object_or_404(DeviceCabin,pk=request.POST.get('cabin_id'),branch=branch)
            name=(request.POST.get('name') or '').strip()[:100]
            if name:
                _,created=PhysicalDevice.objects.get_or_create(
                    branch=branch,name=name,
                    defaults={'device_type':kind,'cabin':cabin},
                )
                messages.success(request,'دستگاه ثبت شد.' if created else 'این نام دستگاه قبلاً ثبت شده است.')
        elif action=='move':
            device=get_object_or_404(PhysicalDevice,pk=request.POST.get('device_id'),branch=branch)
            cabin=get_object_or_404(DeviceCabin,pk=request.POST.get('cabin_id'),branch=branch)
            existing=DeviceSessionBooking.objects.filter(
                Q(device=device)|Q(secondary_device=device),
                status='booked',starts_at__gte=timezone.now(),
            ).exists()
            if existing and device.cabin_id!=cabin.pk:
                messages.error(request,'برای جابه‌جایی دستگاه ابتدا نوبت‌های آینده آن را تعیین تکلیف کنید.')
            else:
                try:
                    start=_parse_time(request.POST.get('work_start') or '08:30')
                    last=_parse_time(request.POST.get('last_start') or '17:30')
                except ValueError:
                    messages.error(request,'ساعت کاری معتبر نیست.')
                else:
                    if start>=last:
                        messages.error(request,'ساعت شروع باید قبل از آخرین شروع نوبت باشد.')
                    else:
                        device.cabin=cabin
                        device.work_start=start
                        device.last_start=last
                        device.save(update_fields=['cabin','work_start','last_start'])
                        messages.success(request,'کابین و ساعت کاری دستگاه ذخیره شد.')
        return redirect(f'/settings/device-capacity/?branch={branch.pk}')

    return render(request,'core/device_capacity_settings.html',{
        'branch':branch,'branches':Branch.objects.filter(is_active=True).order_by('name'),
        'is_admin':_profile(request).role=='admin',
        'types':DeviceTypeSchedule.objects.filter(is_active=True),
        'cabins':DeviceCabin.objects.filter(branch=branch,is_active=True),
        'devices':PhysicalDevice.objects.filter(branch=branch).select_related('device_type','cabin'),
    })


@login_required
def device_booking_schedule(request):
    profile=_profile(request)
    _role_allowed(profile,('consultant','receptionist','admin','manager','internal_manager'))
    branch_id=(request.POST.get('branch') or request.GET.get('branch') or '').strip()
    if profile.role=='admin' and branch_id.isdigit():
        branch=get_object_or_404(Branch,pk=int(branch_id),is_active=True)
    else:
        if not profile.branch_id:
            if profile.role=='admin':
                branch=Branch.objects.filter(is_active=True).order_by('id').first()
                if not branch:
                    raise PermissionDenied('شعبه فعالی وجود ندارد.')
            else:
                raise PermissionDenied('شعبه شما تعریف نشده است.')
        else:
            branch=profile.branch
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
            # A branch-wide DB lock serialises concurrent allocations of cabinets
            # and machines even if two consultants click at the same instant.
            Branch.objects.select_for_update().get(pk=branch.pk)
            item=get_object_or_404(
                ConsultationPlanItem,pk=request.POST.get('plan_item'),
                plan=plan,kind='device',included=True,
            )
            existing=item.device_sessions.exclude(status='cancelled')
            if existing.filter(status='booked').exists():
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
            cabin=get_object_or_404(DeviceCabin,pk=request.POST.get('cabin'),branch=branch,is_active=True)
            device=get_object_or_404(
                PhysicalDevice.objects.select_related('device_type'),
                pk=request.POST.get('device'),branch=branch,is_active=True,
            )
            second_raw=(request.POST.get('secondary_device') or '').strip()
            second=(
                get_object_or_404(PhysicalDevice.objects.select_related('device_type'),
                                  pk=int(second_raw),branch=branch,is_active=True)
                if second_raw.isdigit() else None
            )
            if device.cabin_id!=cabin.pk or (second and second.cabin_id!=cabin.pk):
                messages.error(request,'دستگاه‌های انتخابی باید در کابین رزرو باشند.')
                return redirect(f'/device-bookings/?appointment={appointment.pk}')
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
            treatment=max(m.device_type.treatment_minutes for m in machines)
            preparation=max(m.device_type.preparation_minutes for m in machines)
            treatment_end=start+timedelta(minutes=treatment)
            end=treatment_end+timedelta(minutes=preparation)
            booked=DeviceSessionBooking.objects.filter(
                branch=branch,status__in=('booked','completed'),
                starts_at__lt=end,blocked_until__gt=start,
            )
            machine_ids={m.pk for m in machines}
            collision=booked.filter(
                Q(cabin=cabin) |
                Q(device_id__in=machine_ids) |
                Q(secondary_device_id__in=machine_ids) |
                Q(appointment=appointment),
            ).exists()
            if collision:
                messages.error(request,'در این بازه کابین، دستگاه یا خود بیمار رزرو هم‌پوشان دارد.')
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
        messages.success(request,'نوبت تک‌جلسه‌ای ثبت شد؛ ظرفیت دستگاه و کابین تا پایان آماده‌سازی اشغال است.')
        return redirect(f'/device-bookings/?appointment={appointment.pk}&day={raw_day}')

    bookings=(
        DeviceSessionBooking.objects.filter(branch=branch,starts_at__date=day)
        .exclude(status='cancelled')
        .select_related('appointment','device','secondary_device','cabin','plan_item')
        .order_by('starts_at','cabin__name')
    )
    plans=(
        ConsultationPlan.objects.filter(appointment__branch=branch,
            status__in=('finalized','payment_pending','partial_paid','paid'))
        .select_related('appointment').order_by('-updated_at')[:75]
    )
    return render(request,'core/device_booking_schedule.html',{
        'branch':branch,'day':day,'day_jalali':format_jalali(day),
        'appointment':appointment,'plan':plan,
        'items':plan.items.filter(kind='device',included=True) if plan else [],
        'plans':plans,'bookings':bookings,
        'cabins':DeviceCabin.objects.filter(branch=branch,is_active=True),
        'devices':PhysicalDevice.objects.filter(branch=branch,is_active=True)
          .select_related('device_type','cabin'),
        'can_book':profile.role in ('consultant','admin','manager'),
        'can_manage':profile.role in ('admin','manager','internal_manager'),
        'is_admin':profile.role=='admin',
        'branches':Branch.objects.filter(is_active=True).order_by('name'),
    })


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
