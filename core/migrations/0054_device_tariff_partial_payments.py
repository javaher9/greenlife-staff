from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[
        ('core','0053_consultation_plan'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations=[
        migrations.CreateModel(
            name='DeviceBaseTariff',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('price_toman',models.DecimalField(max_digits=18,decimal_places=0,default=0)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('updated_by',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.SET_NULL,null=True,blank=True,related_name='device_tariff_updates')),
            ],
        ),
        migrations.AlterField(
            model_name='consultationplan',
            name='status',
            field=models.CharField(choices=[
                ('draft','در حال تنظیم'),('finalized','نهایی شده'),
                ('payment_pending','در انتظار پرداخت منشی'),
                ('partial_paid','بیعانه دریافت شده'),
                ('paid','تسویه شده'),('no_sale','فعلاً خرید نکرد'),
            ],db_index=True,default='draft',max_length=24),
        ),
        migrations.RemoveConstraint(
            model_name='financialtransaction',
            name='uniq_finance_appointment',
        ),
    ]
