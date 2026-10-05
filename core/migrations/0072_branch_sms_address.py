from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[('core','0071_visitappointment_no_show')]
    operations=[migrations.AddField(model_name='branch',name='address',field=models.CharField(blank=True,help_text='آدرس قابل استفاده در پیامک نوبت',max_length=300))]
