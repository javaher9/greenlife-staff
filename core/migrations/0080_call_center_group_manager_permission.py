from django.db import migrations, models


LEADERS={'محمد صالحی','فاطمه بابایی'}


def seed_group_managers(apps, schema_editor):
    Profile=apps.get_model('core','EmployeeProfile')
    User=apps.get_model('auth','User')
    for profile in Profile.objects.filter(role='call_center'):
        user=User.objects.filter(pk=profile.user_id).first()
        if not user:
            continue
        name=' '.join(filter(None,[user.first_name,user.last_name])).replace('\u200c',' ').strip()
        name=' '.join(name.split())
        if name in LEADERS:
            profile.can_manage_call_center_groups=True
            profile.save(update_fields=['can_manage_call_center_groups'])


class Migration(migrations.Migration):

    dependencies=[
        ('core','0079_global_call_center_groups'),
    ]

    operations=[
        migrations.AddField(
            model_name='employeeprofile',
            name='can_manage_call_center_groups',
            field=models.BooleanField(
                default=False,
                help_text='اجازه ساخت گروه‌های سراسری کال‌سنتر برای همه گل‌ها.',
            ),
        ),
        migrations.RunPython(seed_group_managers,migrations.RunPython.noop),
    ]
