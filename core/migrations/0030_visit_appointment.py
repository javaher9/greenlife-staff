from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ('core','0029_staff_credential'),
    ]

    operations=[
        migrations.CreateModel(
            name='VisitAppointment',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('full_name',models.CharField(max_length=140)),
                ('phone',models.CharField(db_index=True,max_length=30)),
                ('service',models.CharField(blank=True,max_length=160)),
                ('appointment_date',models.DateField(db_index=True)),
                ('appointment_time',models.TimeField()),
                ('status',models.CharField(choices=[('booked','رزرو شده'),('arrived','مراجعه کرده'),('completed','انجام شد'),('cancelled','لغو شده')],db_index=True,default='booked',max_length=20)),
                ('notes',models.TextField(blank=True)),
                ('source',models.CharField(choices=[('call_center','کال‌سنتر'),('receptionist','منشی'),('admin','مدیریت')],default='call_center',max_length=20)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('branch',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='visit_appointments',to='core.branch')),
                ('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_visit_appointments',to=settings.AUTH_USER_MODEL)),
                ('lead',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='appointments',to='core.referrallead')),
            ],
            options={'ordering':['appointment_date','appointment_time','id']},
        ),
        migrations.AddConstraint(
            model_name='visitappointment',
            constraint=models.UniqueConstraint(
                condition=models.Q(('status','cancelled'),_negated=True),
                fields=('branch','appointment_date','appointment_time'),
                name='uniq_active_visit_appointment_slot',
            ),
        ),
        migrations.AddIndex(
            model_name='visitappointment',
            index=models.Index(fields=['branch','appointment_date','appointment_time'],name='visitappt_branch_day_time_idx'),
        ),
    ]
