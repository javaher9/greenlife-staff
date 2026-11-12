from datetime import datetime
from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone
from core.models import VisitAppointment
from .models import FamilyEnrollment, SchoolProgram


@receiver(post_save, sender=VisitAppointment)
def appointment_changed(sender, instance, **kwargs):
    if kwargs.get('raw'):
        return
    appointment_id = instance.pk
    def sync():
        link = FamilyEnrollment.objects.filter(visit_appointment_id=appointment_id).values('id', 'program_id').first()
        if not link:
            return
        with transaction.atomic():
            SchoolProgram.objects.select_for_update().get(pk=link['program_id'])
            family = FamilyEnrollment.objects.select_for_update().get(pk=link['id'])
            appointment = VisitAppointment.objects.get(pk=appointment_id)
            status = {'booked': 'booked', 'arrived': 'attended', 'completed': 'attended', 'cancelled': 'cancelled', 'no_show': 'cancelled'}.get(appointment.status)
            if status:
                FamilyEnrollment.objects.filter(pk=family.pk).update(status=status, appointment_at=timezone.make_aware(datetime.combine(appointment.appointment_date, appointment.appointment_time)))
    # Main reception transactions release their appointment locks before acquiring school locks.
    transaction.on_commit(sync)
