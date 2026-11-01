"""One-time correction for mistakenly routed overnight leads (Tehran time).

Only untouched new leads are released. Existing call outcomes, follow-ups and
appointment ownership are never changed. No phone or name data is logged.
"""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.db import migrations
from django.utils import timezone


def release_misrouted_overnight_leads(apps, schema_editor):
    Lead = apps.get_model('core', 'ReferralLead')
    Appointment = apps.get_model('core', 'VisitAppointment')
    tz = ZoneInfo('Asia/Tehran')
    window_start = datetime(2026, 10, 31, 20, 0, tzinfo=tz)
    window_end = datetime(2026, 11, 1, 8, 0, tzinfo=tz)
    # This migration may run before 08:00. Never target future records.
    end = min(window_end, timezone.now())

    candidates = Lead.objects.using(schema_editor.connection.alias).filter(
        created_at__gte=window_start,
        created_at__lt=end,
        assigned_at__gte=window_start,
        assigned_at__lt=end,
        assigned_to__isnull=False,
        status='new',
        contact_result='',
        next_follow_up__isnull=True,
        first_appointment_by__isnull=True,
    )
    # Do not release leads already linked to an appointment, including manual
    # follow-ups; those have an active real-world owner.
    protected_ids = Appointment.objects.using(schema_editor.connection.alias).filter(
        lead_id__in=candidates.values('id'),
    ).values('lead_id')
    clean = candidates.exclude(id__in=protected_ids)
    counts = clean.values_list('assigned_to_id', flat=True)
    print('Overnight routing correction: releasing %d unworked leads.' % clean.count())
    clean.update(assigned_to_id=None, assigned_at=None, group_id=None)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0105_body_progress_photos'),
    ]
    operations = [
        migrations.RunPython(release_misrouted_overnight_leads, migrations.RunPython.noop),
    ]
