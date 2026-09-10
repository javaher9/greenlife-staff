from django.db import migrations


GROUP_NAME = 'اینستاگرام جدید'


def create_groups(apps, schema_editor):
    EmployeeProfile = apps.get_model('core', 'EmployeeProfile')
    CallCenterLeadGroup = apps.get_model('core', 'CallCenterLeadGroup')
    for operator in EmployeeProfile.objects.filter(role='call_center', is_active=True):
        CallCenterLeadGroup.objects.get_or_create(
            owner=operator,
            name=GROUP_NAME,
            defaults={'is_default': False},
        )


def remove_groups(apps, schema_editor):
    CallCenterLeadGroup = apps.get_model('core', 'CallCenterLeadGroup')
    CallCenterLeadGroup.objects.filter(name=GROUP_NAME, leads__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0034_first_appointment_owner')]
    operations = [migrations.RunPython(create_groups, remove_groups)]
