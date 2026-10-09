from django.db import migrations


def update_welcome_template(apps,schema_editor):
    Rule=apps.get_model('core','SmsAutomationRule')
    old=('گرین لایف | {name} عزیز، عضویت شما در شبکه فروش فعال شد.\n'
         'نام کاربری: {username}\n'
         'ورود به پنل: {login_url}\n'
         'برای دریافت رمز عبور با معرف خود هماهنگ کنید.')
    new=('گرین لایف | {name} عزیز، عضویت شما در شبکه فروش فعال شد.\n'
         'نام کاربری: {username}\n'
         'رمز ورود: {password}\n'
         'لینک ورود: {login_url}\n'
         'لطفاً رمز را محرمانه نگه دارید.')
    Rule.objects.filter(event='network_member_joined',message_template=old).update(message_template=new)


class Migration(migrations.Migration):
    dependencies=[('core','0077_network_welcome_sms_rule')]
    operations=[migrations.RunPython(update_welcome_template,migrations.RunPython.noop)]
