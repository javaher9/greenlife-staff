from django.db import migrations, models


def grant_eybpoosh_only(apps, schema_editor):
    Profile=apps.get_model('core','EmployeeProfile')
    matches=[]
    for profile in Profile.objects.select_related('user').all().iterator():
        name=' '.join((profile.user.first_name or '',profile.user.last_name or '',profile.user.username or '')).lower()
        compact=''.join(name.replace('ي','ی').replace('ك','ک').replace('‌','').split())
        if any(x in compact for x in ('عیبپوش','ایبپوش','eybpoosh','eybpush','eybposh')):
            matches.append(profile.pk)
    # Do not accidentally grant customer messaging to the wrong account.
    if len(matches)==1:
        Profile.objects.filter(pk=matches[0]).update(can_send_marketing_sms=True)


class Migration(migrations.Migration):
    dependencies=[('core','0080_call_center_group_manager_permission')]
    operations=[
        migrations.AddField(model_name='employeeprofile',name='can_send_marketing_sms',
            field=models.BooleanField(default=False,help_text='اجازه ارسال پیامک تکی و گروهی، بدون دسترسی به تنظیمات درگاه.')),
        migrations.RunPython(grant_eybpoosh_only,migrations.RunPython.noop),
    ]
