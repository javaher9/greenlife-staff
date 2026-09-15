from django.db import migrations


def _norm(value):
    return ' '.join(
        str(value or '')
        .strip()
        .lower()
        .replace('ي', 'ی')
        .replace('ك', 'ک')
        .split()
    )


def restore_kamelia(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    EmployeeProfile = apps.get_model('core', 'EmployeeProfile')

    aliases = (
        'پریسا کلکلی',
        'کلکلی',
        'kolkoli',
        'kalakali',
    )

    matched = []
    for user in User.objects.all().iterator():
        identity = _norm(' '.join(
            part for part in (user.first_name, user.last_name, user.username) if part
        ))
        if any(_norm(alias) in identity for alias in aliases):
            matched.append(user)

    for user in matched:
        if not user.is_active:
            user.is_active = True
            user.save(update_fields=['is_active'])

        profile, _ = EmployeeProfile.objects.get_or_create(
            user=user,
            defaults={
                'role': 'call_center',
                'is_active': True,
            },
        )
        update_fields = []
        if profile.role != 'call_center':
            profile.role = 'call_center'
            update_fields.append('role')
        if not profile.is_active:
            profile.is_active = True
            update_fields.append('is_active')
        if update_fields:
            profile.save(update_fields=update_fields)


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0040_api_server_integration'),
    ]

    operations = [
        migrations.RunPython(restore_kamelia, migrations.RunPython.noop),
    ]
