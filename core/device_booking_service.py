"""Booking service: timing snapshots and atomic physical-resource capacity guards."""
from datetime import date, datetime, timedelta
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from .models import (
    Branch, ConsultationPlanItem, DeviceBooking, DeviceBookingUnit,
    DeviceCabin, DeviceKind, DeviceUnit, FinancialTransaction, VisitAppointment,
)

def _error(message):
    raise ValidationError(message)

@transaction.atomic
def reserve_device_session(*, appointment, plan_item, kind, cabin, units, day, start_time, actor):
    """Lock the branch row to serialize competing reservations on PostgreSQL."""
    branch=Branch.objects.select_for_update().get(pk=appointment.branch_id)
    appointment=VisitAppointment.objects.select_related('consultation_plan').get(pk=appointment.pk)
    plan=getattr(appointment,'consultation_plan',None)
    if not plan or plan.status not in ('partial_paid','paid'):
        _error('ابتدا بیعانه یا تسویه این پکیج را ثبت کنید.')
    if not FinancialTransaction.objects.filter(
        appointment=appointment,source='manual',entry_type='inc',
        review_status__in=('pending','approved'),
    ).exists():
        _error('برای این پکیج هنوز دریافتی ثبت نشده است.')
    plan_item=ConsultationPlanItem.objects.get(pk=plan_item.pk,plan=plan,kind='device',included=True)
    if plan_item.quantity<1:
        _error('تعداد جلسات پکیج معتبر نیست.')
    if plan_item.device_bookings.filter(status='booked').exists():
        _error('برای این خدمت یک نوبت باز دارید؛ ابتدا آن را انجام یا لغو کنید.')
    if plan_item.device_bookings.filter(status='completed').count()>=plan_item.quantity:
        _error('تمام جلسات خریداری‌شده این خدمت انجام شده است.')
    if not kind.is_active or not cabin.is_active or cabin.branch_id!=branch.pk:
        _error('نوع دستگاه یا کابین انتخاب‌شده فعال نیست.')
    unique_ids={unit.pk for unit in units}
    required=2 if 'double define' in plan_item.title.casefold() or 'دابل دیفاین' in plan_item.title else 1
    if len(unique_ids)!=required or len(units)!=required:
        _error('برای دابل دیفاین دقیقاً دو دستگاه DIF70 و برای سایر خدمات یک دستگاه انتخاب کنید.')
    if required==2 and kind.code!='DIF70':
        _error('دابل دیفاین باید با دو دستگاه DIF70 رزرو شود.')
    if any(not unit.is_active or unit.branch_id!=branch.pk or unit.kind_id!=kind.pk for unit in units):
        _error('دستگاه‌های انتخاب‌شده باید فعال، هم‌نوع و متعلق به همین شعبه باشند.')
    if day<timezone.localdate():
        _error('نوبت دستگاه نمی‌تواند در گذشته ثبت شود.')
    if start_time.second or start_time.microsecond or start_time.minute%5:
        _error('شروع نوبت باید روی بازه‌های پنج‌دقیقه‌ای باشد.')
    if start_time<kind.work_start or start_time>kind.last_start:
        _error('ساعت انتخابی خارج از محدوده کاری این دستگاه است.')
    for unit in units:
        if unit.work_start_override and start_time<unit.work_start_override:
            _error(f'دستگاه {unit.name} در این ساعت هنوز فعال نیست.')
        if unit.last_start_override and start_time>unit.last_start_override:
            _error(f'آخرین زمان شروع دستگاه {unit.name} گذشته است.')
    treatment=max(
        (unit.treatment_override_min if unit.treatment_override_min is not None else kind.treatment_minutes)
        for unit in units
    )
    preparation=max(
        (unit.preparation_override_min if unit.preparation_override_min is not None else kind.preparation_minutes)
        for unit in units
    )
    if treatment<1 or treatment>360 or preparation>180:
        _error('مدت درمان یا آماده‌سازی خارج از محدوده مجاز است.')
    start=timezone.make_aware(datetime.combine(day,start_time),timezone.get_current_timezone())
    end=start+timedelta(minutes=treatment+preparation)
    if end.date()!=day or start<timezone.now():
        _error('زمان پایان نوبت نامعتبر است یا ساعت شروع گذشته است.')
    overlapping=DeviceBooking.objects.filter(
        day=day,status='booked',starts_at__lt=end,ends_at__gt=start,
    )
    if overlapping.filter(cabin=cabin).exists():
        _error('این کابین در بازه انتخابی اشغال است.')
    if overlapping.filter(units__pk__in=unique_ids).exists():
        _error('یکی از دستگاه‌های انتخاب‌شده در این بازه اشغال است.')
    if overlapping.filter(appointment__phone=appointment.phone).exists():
        _error('بیمار در این بازه نوبت دستگاه دیگری دارد.')
    booking=DeviceBooking.objects.create(
        appointment=appointment,plan_item=plan_item,branch=branch,
        kind=kind,cabin=cabin,day=day,starts_at=start,ends_at=end,
        treatment_minutes_snapshot=treatment,
        preparation_minutes_snapshot=preparation,created_by=actor,
    )
    DeviceBookingUnit.objects.bulk_create(
        [DeviceBookingUnit(booking=booking,unit=unit) for unit in units]
    )
    return booking
