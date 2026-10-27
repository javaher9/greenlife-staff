from django.db import migrations


def approve_unique_laleh(apps, schema_editor):
    """Re-check the explicitly named remote call-center employee after deploys.

    The earlier 0102 data step may already have run before account alias
    fallback was expanded. Apply only if EXACTLY one active call-center
    profile matches the known operator alias. Never grant to others.
    """
    Profile = apps.get_model('core', 'EmployeeProfile')
    staff = list(Profile.objects.filter(
        role='call_center', is_active=True, user__is_active=True,
    ).select_related('user'))
    def name_words(p):
        u = p.user
        name = ' '.join((u.first_name or '', u.last_name or '', u.username or ''))
        return set(name.replace('ي','ی').replace('ك','ک').replace('_',' ').replace('-',' ').lower().split())
    candidates = [p for p in staff if {'لاله', 'laleh'} & name_words(p)]
    if not candidates:
        candidates = [p for p in staff if 'عباسی' in name_words(p)]
    if len(candidates) == 1:
        Profile.objects.filter(pk=candidates[0].pk).update(remote_attendance_enabled=True)


class Migration(migrations.Migration):
    dependencies = [('core', '0102_call_center_remote_policy')]
    operations = [
        migrations.RunPython(approve_unique_laleh, migrations.RunPython.noop),
    ]
