from django.db import migrations
from django.db.models import Q


def seed_permissions(apps, schema_editor):
    EmployeeProfile = apps.get_model('core', 'EmployeeProfile')
    q = Q(user__is_superuser=True) | Q(role='admin')
    for name in ('هاشمی', 'راد', 'نادری'):
        q |= Q(user__first_name__icontains=name) | Q(user__last_name__icontains=name)
    q |= Q(job_title__icontains='quality') | Q(job_title__icontains='کیفیت')
    EmployeeProfile.objects.filter(q).update(can_register_instagram_dm_lead=True)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0065_instagram_dm_lead_permission'),
    ]

    operations = [
        migrations.RunPython(seed_permissions, migrations.RunPython.noop),
    ]
