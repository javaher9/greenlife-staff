from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0052_payroll_system'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='ConsultationPlan',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('status', models.CharField(choices=[('draft','در حال تنظیم'),('finalized','نهایی شده'),('payment_pending','در انتظار پرداخت منشی'),('paid','پرداخت شده'),('no_sale','فعلاً خرید نکرد')], db_index=True, default='draft', max_length=24)),
                ('subtotal_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('discount_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('final_amount_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('note', models.TextField(blank=True)),
                ('finalized_at', models.DateTimeField(blank=True, null=True)),
                ('sent_to_reception_at', models.DateTimeField(blank=True, null=True)),
                ('paid_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('appointment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='consultation_plan', to='core.visitappointment')),
                ('consultant', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='consultation_plans', to=settings.AUTH_USER_MODEL)),
                ('paid_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='paid_consultation_plans', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-updated_at','-id']},
        ),
        migrations.CreateModel(
            name='ConsultationPlanItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('kind', models.CharField(choices=[('diet','رژیم'),('device','دستگاه'),('lipolytic','لیپولیتیک'),('other','سایر')], default='other', max_length=20)),
                ('source', models.CharField(choices=[('doctor','پیشنهاد پزشک'),('consultant','افزوده مشاور')], default='consultant', max_length=20)),
                ('source_pk', models.PositiveBigIntegerField(blank=True, null=True)),
                ('title', models.CharField(max_length=180)),
                ('area', models.CharField(blank=True, max_length=140)),
                ('quantity', models.PositiveSmallIntegerField(default=1)),
                ('unit_price_toman', models.DecimalField(decimal_places=0, default=0, max_digits=18)),
                ('included', models.BooleanField(default=True)),
                ('note', models.TextField(blank=True)),
                ('doctor_snapshot', models.JSONField(blank=True, default=dict)),
                ('sort_order', models.PositiveSmallIntegerField(default=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('plan', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='items', to='core.consultationplan')),
            ],
            options={'ordering':['sort_order','id']},
        ),
    ]
