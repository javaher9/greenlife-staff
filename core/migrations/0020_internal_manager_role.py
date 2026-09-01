from django.db import migrations, models


def assign_internal_manager(apps, schema_editor):
    EmployeeProfile = apps.get_model('core', 'EmployeeProfile')
    EmployeeProfile.objects.filter(
        user__first_name='فاطیما',
        user__last_name='هاشمی',
        branch__name='نیاوران',
    ).update(role='internal_manager', job_title='مدیر داخلی')


def restore_branch_manager(apps, schema_editor):
    EmployeeProfile = apps.get_model('core', 'EmployeeProfile')
    EmployeeProfile.objects.filter(
        user__first_name='فاطیما',
        user__last_name='هاشمی',
        branch__name='نیاوران',
        role='internal_manager',
    ).update(role='manager')


class Migration(migrations.Migration):
    dependencies = [('core', '0019_blackboardmessage')]

    operations = [
        migrations.AlterField(
            model_name='employeeprofile',
            name='role',
            field=models.CharField(
                choices=[
                    ('admin', 'مدیر سیستم'),
                    ('internal_manager', 'مدیر داخلی'),
                    ('manager', 'مدیر شعبه'),
                    ('employee', 'کارمند'),
                    ('referrer', 'معرف مشتری'),
                ],
                default='employee',
                max_length=20,
            ),
        ),
        migrations.RunPython(assign_internal_manager, restore_branch_manager),
    ]
