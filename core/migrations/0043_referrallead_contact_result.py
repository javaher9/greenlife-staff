from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('core','0042_backfill_call_center_sales')]
    operations=[migrations.AddField(model_name='referrallead',name='contact_result',field=models.CharField(blank=True,choices=[('follow_up','نیاز به پیگیری'),('appointment','نوبت داده شد'),('no_answer','پاسخ نداد'),('won','فروش موفق'),('sale_lost','فروش ناموفق'),('not_interested','تمایل ندارد')],db_index=True,max_length=20))]
