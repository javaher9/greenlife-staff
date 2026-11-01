"""Guarantee a visible, manual-only Gandom slot in lead management.

This account is non-login until an administrator explicitly configures credentials.
Automatic routing is governed by its separate explicit rotation allowlist.
"""
from django.db import migrations


def ensure_gandom(apps, schema_editor):
    User=apps.get_model('auth','User')
    EmployeeProfile=apps.get_model('core','EmployeeProfile')
    profiles=EmployeeProfile.objects.select_related('user').all()
    for p in profiles:
        identity=' '.join((p.user.first_name or '',p.user.last_name or '',p.user.username or '',p.job_title or '')).lower()
        if 'گندم' in identity or 'gandom' in identity or 'gandam' in identity:
            # An existing account may have been disabled intentionally;
            # do not change its active state or access rights.
            return
    username='flower-gandom'
    if User.objects.filter(username=username).exists():
        return
    user=User(username=username,first_name='گل',last_name='گندم',is_active=True)
    user.set_unusable_password()
    user.save()
    EmployeeProfile.objects.create(user=user,role='call_center',is_active=True,job_title='گل گندم')


class Migration(migrations.Migration):
    dependencies=[('core','0106_release_overnight_misrouted_leads')]
    operations=[migrations.RunPython(ensure_gandom,migrations.RunPython.noop)]
