from django.db import migrations


def grant_coordinator(apps, schema_editor):
    Profile = apps.get_model('core', 'EmployeeProfile')
    matches = []
    def normalized(value):
        return ''.join((value or '').replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', '').split()).lower()
    for p in Profile.objects.filter(is_active=True, user__is_active=True, role='consultant', branch__is_active=True).select_related('user', 'branch'):
        if normalized(p.branch.name) not in ('نیاوران', 'تهراننیاوران', 'niavaran'):
            continue
        if normalized(p.user.last_name) == 'مرادی' or normalized(p.user.username) == 'moradi':
            matches.append(p)
    # Never grant every consultant or guess among ambiguous accounts.
    if len(matches) == 1:
        Profile.objects.filter(pk=matches[0].pk).update(can_manage_schools=True)


class Migration(migrations.Migration):
    dependencies = [('core', '0120_employeeprofile_can_manage_schools')]
    operations = [migrations.RunPython(grant_coordinator, migrations.RunPython.noop)]
