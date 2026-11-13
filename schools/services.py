from django.utils import timezone
from core.models import VisitAppointment


def sync_appointment(enrollment, user):
    """Book the adult's family visit; never merge children into phone-keyed patient records."""
    if enrollment.status not in ('booked', 'attended'):
        if enrollment.visit_appointment_id:
            appointment = enrollment.visit_appointment
            if appointment.status not in ('cancelled', 'no_show'):
                appointment.status = 'cancelled'
                appointment.save()
            if enrollment.status != 'cancelled':
                enrollment.visit_appointment = None
        return
    at = timezone.localtime(enrollment.appointment_at)
    appointment = enrollment.visit_appointment if enrollment.visit_appointment_id else VisitAppointment(created_by=user)
    appointment.branch = enrollment.program.organization.branch
    appointment.full_name = enrollment.parent_name
    appointment.phone = enrollment.member.phone
    appointment.service = 'طرح مدارس · مراجعه خانواده'
    appointment.appointment_date = at.date()
    appointment.appointment_time = at.time().replace(tzinfo=None)
    appointment.status = 'arrived' if enrollment.status == 'attended' else 'booked'
    appointment.source = 'admin'
    appointment.notes = f'طرح مدارس؛ والد همراه. پرونده فرزندان در بخش مدارس / پرونده رشد. شناسه خانواده: {enrollment.pk}'
    appointment.save()
    enrollment.visit_appointment = appointment
