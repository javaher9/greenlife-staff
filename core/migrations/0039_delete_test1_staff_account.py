from django.db import migrations


def delete_test_staff_account(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    User.objects.filter(pk=77, username__iexact='Test1').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0038_excuse_20260912_power_outage_lateness'),
    ]

    operations = [
        migrations.RunPython(delete_test_staff_account, migrations.RunPython.noop),
    ]
