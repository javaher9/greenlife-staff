from django.db import migrations


TARGET_NAME = 'حسنیفروزش'


def _norm(value):
    value = (value or '').strip().lower()
    value = value.replace('ي','ی').replace('ك','ک').replace('\u200c','').replace(' ','').replace('-','')
    return value


def set_hosni_foroughesh_receptionist(apps, schema_editor):
    EmployeeProfile = apps.get_model('core','EmployeeProfile')

    candidates = []
    for profile in EmployeeProfile.objects.select_related('user','branch').all():
        branch_name = _norm(getattr(profile.branch,'name',''))
        in_poonak = ('پونک' in branch_name) or ('poonak' in branch_name) or ('punak' in branch_name)
        if not in_poonak:
            continue

        first = _norm(profile.user.first_name)
        last = _norm(profile.user.last_name)
        username = _norm(profile.user.username)
        job_title = _norm(profile.job_title)

        full_forward = first + last
        full_reverse = last + first
        exact_name = TARGET_NAME in (full_forward, full_reverse)
        fallback_foroughesh = ('فروزش' in first) or ('فروزش' in last) or ('فروزش' in username) or ('فروزش' in job_title)

        if exact_name or fallback_foroughesh:
            candidates.append(profile)

    if len(candidates) == 1:
        profile = candidates[0]
        old_role = profile.role
        profile.role = 'receptionist'
        profile.save(update_fields=['role'])
        print(f'ROLE_UPDATE_OK id={profile.pk} username={profile.user.username} branch={profile.branch} old_role={old_role} new_role=receptionist')
    elif len(candidates) == 0:
        print('ROLE_UPDATE_SKIPPED no matching Hosni Foroughesh profile found in Poonak')
    else:
        ids = ','.join(str(x.pk) for x in candidates)
        print(f'ROLE_UPDATE_SKIPPED ambiguous matches ids={ids}')


class Migration(migrations.Migration):
    dependencies = [
        ('core','0027_call_center_lead_groups'),
    ]

    operations = [
        migrations.RunPython(set_hosni_foroughesh_receptionist, migrations.RunPython.noop),
    ]
