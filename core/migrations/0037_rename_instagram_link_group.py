from django.db import migrations


def rename_instagram_group(apps, schema_editor):
    CallCenterLeadGroup = apps.get_model('core', 'CallCenterLeadGroup')
    CallCenterLeadGroup.objects.filter(name='اینستاگرام جدید').update(name='اینستاگرام - لینک')


def reverse_rename_instagram_group(apps, schema_editor):
    CallCenterLeadGroup = apps.get_model('core', 'CallCenterLeadGroup')
    CallCenterLeadGroup.objects.filter(name='اینستاگرام - لینک').update(name='اینستاگرام جدید')


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0036_referral_supervisor_role'),
    ]

    operations = [
        migrations.RunPython(rename_instagram_group, reverse_rename_instagram_group),
    ]
