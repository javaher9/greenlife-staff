"""Send one day-before reminder for each booked device session."""
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from core.jalali import format_jalali
from core.models import ApiServerSettings, DeviceBooking
from core.sms import send_sms


class Command(BaseCommand):
    help='Send idempotent day-before SMS reminders for device sessions'

    def handle(self,*args,**options):
        config=ApiServerSettings.load()
        if not (config.is_enabled and config.is_configured and config.appointment_confirmation_enabled):
            self.stdout.write('Device reminders disabled: SMS gateway/confirmation is not configured.')
            return
        target=timezone.localdate()+timedelta(days=1)
        sent=0
        bookings=DeviceBooking.objects.filter(
            day=target,status='booked',reminder_sent_at__isnull=True,
        ).select_related('appointment','kind','branch','cabin')
        for booking in bookings.iterator():
            if not booking.appointment.phone:
                continue
            body=(
                f'یادآوری نوبت گرین لایف\n{booking.appointment.full_name} عزیز،'
                f' فردا {format_jalali(booking.day)} ساعت '
                f'{timezone.localtime(booking.starts_at):%H:%M} '
                f'برای {booking.kind.label} در {booking.branch.name} '
                f'({booking.cabin.name}) نوبت دارید.\n'
                f'کد نوبت دستگاه: {booking.pk}\n02134247'
            )
            try:
                send_sms(
                    booking.appointment.phone,body,purpose='appointment',
                    created_by=booking.created_by,appointment=booking.appointment,
                )
                DeviceBooking.objects.filter(
                    pk=booking.pk,reminder_sent_at__isnull=True,
                ).update(reminder_sent_at=timezone.now())
                sent+=1
            except Exception as exc:
                self.stderr.write(f'Reminder for device booking {booking.pk} failed: {exc}')
        self.stdout.write(f'Device reminders accepted: {sent}')
