from django.db import migrations, models


def enable_unique_remote_laleh(apps, schema_editor):
    """Honor the named remote call-center operator without relaxing other users.

    Match only active call-center accounts and require exactly one candidate.
    If there is ambiguity, leave access disabled for a manager to review.
    """
    Profile = apps.get_model('core', 'EmployeeProfile')
    candidates = list(
        Profile.objects.filter(
            role='call_center', is_active=True, user__is_active=True,
        ).select_related('user')
    )
    def words(profile):
        user = profile.user
        label = ' '.join((user.first_name or '', user.last_name or '', user.username or ''))
        return set(label.replace('ي', 'ی').replace('ك', 'ک').replace('_', ' ').replace('-', ' ').lower().split())

    named = [p for p in candidates if 'لاله' in words(p) or 'laleh' in words(p)]
    if not named:
        named = [
            p for p in candidates
            if 'عباسی' in words(p)
        ]
    if len(named) == 1:
        Profile.objects.filter(pk=named[0].pk).update(remote_attendance_enabled=True)


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0101_consultant_booking_remote_attendance'),
    ]

    operations = [
        migrations.AlterField(
            model_name='employeeprofile',
            name='remote_attendance_enabled',
            field=models.BooleanField(
                default=False,
                help_text='مجوز فردی دورکاری: ورود و خروج از راه دور بدون GPS شعبه، با ثبت استراحت. فقط برای کال‌سنتر.',
            ),
        ),
        migrations.AlterField(
            model_name='visitappointment',
            name='source',
            field=models.CharField(
                max_length=20, default='call_center',
                choices=[
                    ('call_center', 'کال‌سنتر'),
                    ('receptionist', 'منشی'),
                    ('admin', 'مدیریت'),
                ],
            ),
        ),
        migrations.RunPython(enable_unique_remote_laleh, migrations.RunPython.noop),
    ]
