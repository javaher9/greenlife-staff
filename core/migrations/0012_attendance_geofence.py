from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('core','0011_dailyreport_submission_id')]
    operations=[
        migrations.AddField(model_name='branch',name='latitude',field=models.DecimalField(blank=True,decimal_places=6,max_digits=9,null=True)),
        migrations.AddField(model_name='branch',name='longitude',field=models.DecimalField(blank=True,decimal_places=6,max_digits=9,null=True)),
        migrations.AddField(model_name='branch',name='attendance_radius_m',field=models.PositiveIntegerField(default=150)),
        migrations.AddField(model_name='branch',name='geofence_enabled',field=models.BooleanField(default=False)),
        migrations.AddField(model_name='attendance',name='check_in_latitude',field=models.DecimalField(blank=True,decimal_places=6,max_digits=9,null=True)),
        migrations.AddField(model_name='attendance',name='check_in_longitude',field=models.DecimalField(blank=True,decimal_places=6,max_digits=9,null=True)),
        migrations.AddField(model_name='attendance',name='check_in_accuracy_m',field=models.FloatField(blank=True,null=True)),
        migrations.AddField(model_name='attendance',name='check_in_distance_m',field=models.PositiveIntegerField(blank=True,null=True)),
        migrations.AddField(model_name='attendance',name='check_in_location_status',field=models.CharField(choices=[('verified','تأیید موقعیت'),('outside','خارج محدوده'),('low_accuracy','دقت پایین'),('unavailable','موقعیت ناموجود'),('manual','ثبت دستی مدیر'),('legacy','قدیمی')],default='legacy',max_length=20)),
    ]
