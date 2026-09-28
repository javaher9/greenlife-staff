from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from core.jalali import format_jalali
from core.models import ApiServerSettings, DeviceSessionBooking
from core.sms import send_sms


class Command(BaseCommand):
    help='ارسال یادآوری نوبت‌های دستگاه در ۲۴ ساعت آینده؛ قابل اجرای دوره‌ای'

    def handle(self,*args,**options):
        cfg=ApiServerSettings.load()
        if not (cfg.is_enabled and cfg.appointment_confirmation_enabled and cfg.is_configured):
            self.stdout.write('SMS gateway or confirmation is disabled.')
            return
        now=timezone.now()
        ids=list(DeviceSessionBooking.objects.filter(
            status='booked',reminder_sent_at__isnull=True,
            starts_at__gt=now+timedelta(hours=1),
            starts_at__lte=now+timedelta(hours=24),
        ).values_list('pk',flat=True)[:150])
        sent=0
        for pk in ids:
            with transaction.atomic():
                booking=DeviceSessionBooking.objects.select_for_update().select_related(
                    'appointment','branch','device'
                ).get(pk=pk)
                if booking.reminder_sent_at or booking.status!='booked':
                    continue
                time_local=timezone.localtime(booking.starts_at)
                body=(
                    f'گرین لایف\n{booking.appointment.full_name} عزیز، یادآوری نوبت '
                    f'{booking.device.device_type.name} شما در {booking.branch.name} '
                    f'تاریخ {format_jalali(time_local.date())} '
                    f'ساعت {time_local:%H:%M}.\n02134247'
                )
                try:
                    send_sms(booking.appointment.phone,body,purpose='appointment',
                             appointment=booking.appointment,created_by=booking.created_by)
                except Exception:
                    continue
                booking.reminder_sent_at=timezone.now()
                booking.save(update_fields=['reminder_sent_at','updated_at'])
                sent+=1
        self.stdout.write(self.style.SUCCESS(f'{sent} یادآوری ارسال شد.'))
