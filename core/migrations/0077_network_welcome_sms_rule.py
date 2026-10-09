from django.db import migrations


def enable_network_welcome_sms(apps, schema_editor):
    SmsAutomationRule=apps.get_model('core', 'SmsAutomationRule')
    SmsAutomationRule.objects.get_or_create(
        event='network_member_joined',
        defaults={
            'is_enabled':True,
            'recipient':'patient',
            'timing':'immediate',
            'offset':0,
            'offset_unit':'minutes',
            'message_template':(
                'گرین لایف | {name} عزیز، عضویت شما در شبکه فروش فعال شد.\n'
                'نام کاربری: {username}\n'
                'ورود به پنل: {login_url}\n'
                'برای دریافت رمز عبور با معرف خود هماهنگ کنید.'
            ),
        },
    )


class Migration(migrations.Migration):
    dependencies=[
        ('core','0076_unify_appointment_label'),
    ]

    operations=[
        migrations.RunPython(enable_network_welcome_sms, migrations.RunPython.noop),
    ]
