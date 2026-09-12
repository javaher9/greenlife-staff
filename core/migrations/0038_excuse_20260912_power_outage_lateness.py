from datetime import date

from django.db import migrations


OUTAGE_DATE = date(2026, 9, 12)
LATE_USER_IDS = [6, 8, 9, 16, 18, 19, 21, 23, 26, 27, 28, 29, 30, 33, 115]


def excuse_power_outage_lateness(apps, schema_editor):
    Attendance = apps.get_model('core', 'Attendance')
    Attendance.objects.filter(
        date=OUTAGE_DATE,
        user_id__in=LATE_USER_IDS,
        status='late',
    ).update(status='present')


def restore_original_lateness(apps, schema_editor):
    Attendance = apps.get_model('core', 'Attendance')
    Attendance.objects.filter(
        date=OUTAGE_DATE,
        user_id__in=LATE_USER_IDS,
        status='present',
    ).update(status='late')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0037_rename_instagram_link_group'),
    ]

    operations = [
        migrations.RunPython(excuse_power_outage_lateness, restore_original_lateness),
    ]
