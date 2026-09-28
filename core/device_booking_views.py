"""Branch device/cabin settings and single-session treatment reservations."""
from datetime import date, time

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .device_booking_service import reserve_device_session
from .jalali import format_jalali
from .models import (
    ApiServerSettings, Branch, DeviceBooking, DeviceCabin, DeviceKind,
    DeviceUnit, VisitAppointment,
)
from .sms import send_sms

BOOKING_ROLES={'admin','manager','internal_manager','consultant','receptionist'}
SETTING_ROLES={'admin','manager','internal_manager'}


def _role(request):
    return getattr(getattr(request.user,'profile',None),'role','employee')


def _branch(request):
    profile=getattr(request.user,'profile',None)
    if _role(request)=='admin':
        raw=(request.POST.get('branch') or request.GET.get('branch') or '').strip()
        branch=Branch.objects.filter(pk=int(raw),is_active=True).first() if raw.isdigit() else None
        return branch or Branch.objects.filter(is_active=True).order_by('id').first()
    return profile.branch if profile and profile.branch_id else None


def _send_booking_message(booking,kind):
    config=ApiServerSettings.load()
    if not (config.is_enabled and config.is_configured and config.appointment_confirmation_enabled):
        return False
    when=timezone.localtime(booking.starts_at)
    text={
        'confirm':'نوبت شما ثبت شد',
        'cancel':'نوبت شما لغو شد',
    }[kind]
    body=(
        f'گرین لایف\n{booking.appointment.full_name} عزیز، {text}.\n'
        f'{booking.kind.label} · {booking.branch.name} · {booking.cabin.name}\n'
        f'{format_jalali(booking.day)} ساعت {when:%H:%M}\n'
        f'کد نوبت دستگاه: {booking.pk}\n02134247'
    )
    try:
        send_sms(
            booking.appointment.phone,body,purpose='appointment',
            created_by=booking.created_by,appointment=booking.appointment,
        )
        if kind=='confirm':
            booking.confirmation_sent_at=timezone.now()
            booking.save(update_fields=['confirmation_sent_at','updated_at'])
        return True
    except Exception:
        return False


@login_required
def device_booking_schedule(request):
    if _role(request) not in BOOKING_ROLES:
        raise PermissionDenied('دسترسی تقویم دستگاه برای این نقش فعال نیست.')
    branch=_branch(request)
    if not branch:
        messages.error(request,'شعبه فعال برای شما مشخص نشده است.')
        return redirect('dashboard')
    raw_day=request.POST.get('day') or request.GET.get('day') or ''
    try:
        selected_day=date.fromisoformat(raw_day) if raw_day else timezone.localdate()
    except ValueError:
        selected_day=timezone.localdate()

    eligible=VisitAppointment.objects.filter(
        branch=branch,
        consultation_plan__status__in=('partial_paid','paid'),
    ).exclude(status='cancelled').select_related('consultation_plan').prefetch_related(
        'consultation_plan__items',
    ).order_by('-appointment_date','-id')
    raw_visit=request.POST.get('appointment_id') or request.GET.get('appointment') or ''
    selected_visit=eligible.filter(pk=int(raw_visit)).first() if raw_visit.isdigit() else None
    eligible=eligible[:150]

    if request.method=='POST':
        action=request.POST.get('action') or ''
        if action=='book':
            if not selected_visit:
                messages.error(request,'پرونده دارای بیعانه یا تسویه را انتخاب کنید.')
            else:
                try:
                    raw_item=request.POST.get('plan_item_id') or ''
                    raw_kind=request.POST.get('kind_id') or ''
                    raw_cabin=request.POST.get('cabin_id') or ''
                    raw_units=request.POST.getlist('unit_ids')
                    if not all((raw_item.isdigit(),raw_kind.isdigit(),raw_cabin.isdigit())):
                        raise ValidationError('خدمت، نوع دستگاه و کابین را انتخاب کنید.')
                    if not raw_units or any(not item.isdigit() for item in raw_units):
                        raise ValidationError('دستگاه فیزیکی را انتخاب کنید.')
                    kind=get_object_or_404(DeviceKind,pk=int(raw_kind),is_active=True)
                    cabin=get_object_or_404(DeviceCabin,pk=int(raw_cabin),branch=branch,is_active=True)
                    units=list(DeviceUnit.objects.filter(
                        pk__in=[int(x) for x in raw_units],branch=branch,is_active=True,
                        kind=kind,
                    ))
                    if len(units)!=len(set(raw_units)):
                        raise ValidationError('دستگاه انتخاب‌شده معتبر نیست.')
                    item=get_object_or_404(
                        selected_visit.consultation_plan.items,
                        pk=int(raw_item),kind='device',included=True,
                    )
                    starts=time.fromisoformat(request.POST.get('start_time') or '')
                    booking=reserve_device_session(
                        appointment=selected_visit,plan_item=item,kind=kind,
                        cabin=cabin,units=units,day=selected_day,
                        start_time=starts,actor=request.user,
                    )
                    messages.success(request,'نوبت ثبت شد؛ زمان درمان و آماده‌سازی این نوبت ثابت می‌ماند.')
                    if not _send_booking_message(booking,'confirm'):
                        messages.warning(request,'نوبت محفوظ است؛ پیامک تأیید ارسال نشد. تنظیمات سامانه پیامک را بررسی کنید.')
                except (ValueError,ValidationError) as exc:
                    text='؛ '.join(exc.messages) if isinstance(exc,ValidationError) else 'زمان یا دستگاه معتبر نیست.'
                    messages.error(request,text)
                except IntegrityError:
                    messages.error(request,'این بازه هم‌زمان رزرو شده است. صفحه را تازه‌سازی کنید.')
        elif action in ('complete','cancel'):
            raw_booking=(request.POST.get('booking_id') or '').strip()
            if raw_booking.isdigit():
                booking=get_object_or_404(DeviceBooking,pk=int(raw_booking),branch=branch)
                if booking.status=='booked':
                    if action=='complete' and booking.starts_at>timezone.now():
                        messages.error(request,'جلسه‌ای که هنوز شروع نشده قابل تکمیل نیست.')
                    else:
                        booking.status='completed' if action=='complete' else 'cancelled'
                        booking.save(update_fields=['status','updated_at'])
                        if action=='cancel' and not _send_booking_message(booking,'cancel'):
                            messages.warning(request,'لغو ثبت شد، اما پیامک لغو ارسال نشد.')
                        else:
                            messages.success(request,'وضعیت جلسه ثبت شد.')
                else:
                    messages.info(request,'وضعیت این نوبت قبلاً تغییر کرده است.')
        return redirect(f"{reverse('device_booking_schedule')}?branch={branch.pk}&day={selected_day.isoformat()}&appointment={raw_visit}")

    cabins=list(DeviceCabin.objects.filter(branch=branch,is_active=True))
    kinds=list(DeviceKind.objects.filter(is_active=True).order_by('code'))
    units=list(DeviceUnit.objects.filter(branch=branch,is_active=True).select_related('kind','home_cabin'))
    rows=list(DeviceBooking.objects.filter(branch=branch,day=selected_day).exclude(
        status='cancelled',
    ).select_related('appointment','kind','cabin','plan_item').prefetch_related(
        'units',
    ).order_by('starts_at','cabin__name'))
    for row in rows:
        row.local_start=timezone.localtime(row.starts_at)
        row.local_end=timezone.localtime(row.ends_at)
    return render(request,'core/device_booking_schedule.html',{
        'branch':branch,'branches':Branch.objects.filter(is_active=True).order_by('name'),
        'is_admin':_role(request)=='admin','is_manager':_role(request) in SETTING_ROLES,
        'day':selected_day,'day_label':format_jalali(selected_day),
        'eligible':eligible,'selected_visit':selected_visit,
        'selected_items':list(selected_visit.consultation_plan.items.filter(kind='device',included=True))
            if selected_visit else [],
        'cabins':cabins,'kinds':kinds,'units':units,'bookings':rows,
    })


@login_required
def device_booking_settings(request):
    if _role(request) not in SETTING_ROLES:
        raise PermissionDenied('تنظیمات دستگاه فقط برای مدیریت فعال است.')
    branch=_branch(request)
    if not branch:
        messages.error(request,'ابتدا یک شعبه فعال تعریف کنید.')
        return redirect('dashboard')
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='kind':
            if _role(request)!='admin':
                raise PermissionDenied('تنظیمات عمومی زمان دستگاه فقط برای ادمین است.')
            kind=get_object_or_404(DeviceKind,pk=request.POST.get('kind_id'))
            try:
                treatment=int(request.POST.get('treatment_minutes') or '')
                preparation=int(request.POST.get('preparation_minutes') or '')
                work_start=time.fromisoformat(request.POST.get('work_start') or '')
                last_start=time.fromisoformat(request.POST.get('last_start') or '')
                if not (1<=treatment<=360 and 0<=preparation<=180):
                    raise ValueError()
                if not (time(8,30)<=work_start<=last_start<=time(17,30)):
                    raise ValueError()
                kind.treatment_minutes=treatment
                kind.preparation_minutes=preparation
                kind.work_start=work_start
                kind.last_start=last_start
                kind.save(update_fields=[
                    'treatment_minutes','preparation_minutes','work_start','last_start',
                ])
                messages.success(request,'زمان‌های جدید فقط در رزروهای آینده اعمال می‌شوند.')
            except ValueError:
                messages.error(request,'مدت یا ساعت دستگاه معتبر نیست؛ شروع از ۸:۳۰ و آخرین شروع تا ۱۷:۳۰ است.')
        elif action=='cabin':
            name=(request.POST.get('cabin_name') or '').strip()[:110]
            if not name:
                messages.error(request,'نام کابین را وارد کنید.')
            else:
                try:
                    DeviceCabin.objects.create(branch=branch,name=name)
                    messages.success(request,'کابین ثبت شد.')
                except IntegrityError:
                    messages.error(request,'این نام کابین در شعبه قبلاً وجود دارد.')
        elif action=='unit':
            name=(request.POST.get('unit_name') or '').strip()[:110]
            raw_kind=request.POST.get('kind_id') or ''
            raw_cabin=request.POST.get('home_cabin') or ''
            if not name or not raw_kind.isdigit():
                messages.error(request,'نام و نوع دستگاه را وارد کنید.')
            else:
                kind=get_object_or_404(DeviceKind,pk=int(raw_kind))
                home=DeviceCabin.objects.filter(pk=int(raw_cabin),branch=branch).first() if raw_cabin.isdigit() else None
                try:
                    DeviceUnit.objects.create(branch=branch,kind=kind,name=name,home_cabin=home)
                    messages.success(request,'دستگاه فیزیکی ثبت شد.')
                except IntegrityError:
                    messages.error(request,'نام دستگاه در این شعبه تکراری است.')
        elif action=='unit_schedule':
            unit=get_object_or_404(DeviceUnit,pk=request.POST.get('unit_id'),branch=branch)
            try:
                raw_treat=(request.POST.get('treatment_override_min') or '').strip()
                raw_prep=(request.POST.get('preparation_override_min') or '').strip()
                raw_start=(request.POST.get('work_start_override') or '').strip()
                raw_last=(request.POST.get('last_start_override') or '').strip()
                treat=int(raw_treat) if raw_treat else None
                prep=int(raw_prep) if raw_prep else None
                first=time.fromisoformat(raw_start) if raw_start else None
                last=time.fromisoformat(raw_last) if raw_last else None
                if treat is not None and not (1<=treat<=360):
                    raise ValueError()
                if prep is not None and not (0<=prep<=180):
                    raise ValueError()
                if first and not (time(8,30)<=first<=time(17,30)):
                    raise ValueError()
                if last and not (time(8,30)<=last<=time(17,30)):
                    raise ValueError()
                if first and last and first>last:
                    raise ValueError()
                unit.treatment_override_min=treat
                unit.preparation_override_min=prep
                unit.work_start_override=first
                unit.last_start_override=last
                unit.save(update_fields=[
                    'treatment_override_min','preparation_override_min',
                    'work_start_override','last_start_override',
                ])
                messages.success(request,'برنامه اختصاصی دستگاه برای رزروهای آینده ذخیره شد.')
            except ValueError:
                messages.error(request,'مدت یا ساعت اختصاصی دستگاه معتبر نیست.')
        elif action=='move':
            unit=get_object_or_404(DeviceUnit,pk=request.POST.get('unit_id'),branch=branch)
            raw=request.POST.get('home_cabin') or ''
            unit.home_cabin=DeviceCabin.objects.filter(pk=int(raw),branch=branch).first() if raw.isdigit() else None
            unit.save(update_fields=['home_cabin'])
            messages.success(request,'کابین پیش‌فرض دستگاه تغییر کرد؛ رزروهای قبلی بدون تغییر باقی ماندند.')
        return redirect(f"{reverse('device_booking_settings')}?branch={branch.pk}")

    return render(request,'core/device_booking_settings.html',{
        'branch':branch,'branches':Branch.objects.filter(is_active=True).order_by('name'),
        'is_admin':_role(request)=='admin',
        'kinds':DeviceKind.objects.all().order_by('code'),
        'cabins':DeviceCabin.objects.filter(branch=branch).order_by('name'),
        'units':DeviceUnit.objects.filter(branch=branch).select_related('kind','home_cabin').order_by('name'),
    })
