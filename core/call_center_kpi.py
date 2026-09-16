from django.utils import timezone

from .models import VisitAppointment


def due_call_center_appointment_counts(operator, month_start, today=None):
    """Return booked/due and arrived lead counts without treating future bookings as misses."""
    today=today or timezone.localdate()
    due=(VisitAppointment.objects.filter(
        lead__assigned_to=operator,source='call_center',appointment_date__gte=month_start,
        appointment_date__lte=today,
    ).exclude(status='cancelled').exclude(lead__isnull=True))
    due_count=due.values('lead_id').distinct().count()
    visit_count=due.filter(status__in=('arrived','completed')).values('lead_id').distinct().count()
    return due_count,visit_count
