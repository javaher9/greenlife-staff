from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('core','0098_target_percent_policy')]
    operations=[migrations.AddField(model_name='employeeprofile',name='can_request_payments',field=models.BooleanField(default=False,help_text='اجازه ثبت درخواست پرداخت و تنخواه توسط مدیریت'))]
