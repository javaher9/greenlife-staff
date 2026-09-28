from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0053_consultation_plan'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SmsAutomationRule',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event', models.CharField(choices=[
                    ('appointment_booked','ثبت نوبت'),('appointment_reminder','یادآوری نوبت'),
                    ('appointment_changed','تغییر نوبت'),('appointment_cancelled','لغو نوبت'),
                    ('patient_arrived','مراجعه بیمار'),('payment_approved','تأیید پرداخت'),
                    ('payment_due','یادآوری پرداخت'),('device_session_booked','رزرو جلسه دستگاه'),
                    ('device_session_reminder','یادآوری جلسه دستگاه'),
                    ('device_session_started','شروع جلسه دستگاه'),
                    ('device_session_finished','پایان جلسه دستگاه'),
                    ('treatment_followup','پیگیری پس از درمان'),('lead_new','لید جدید'),
                    ('lead_overdue','تأخیر در تماس با لید'),('staff_late','تأخیر حضور پرسنل'),
                    ('staff_task_due','سررسید وظیفه'),('internal_approval','مصوبه یا تأیید مدیریتی'),
                ], max_length=50, unique=True)),
                ('is_enabled', models.BooleanField(default=False)),
                ('recipient', models.CharField(choices=[
                    ('patient','شماره بیمار / مشتری'),('executive','شماره مدیریت'),
                    ('internal_manager','شماره مدیر داخلی'),('staff','شماره پرسنل مرتبط'),
                    ('custom','شماره مشخص'),
                ], default='patient', max_length=24)),
                ('custom_number', models.CharField(blank=True,max_length=20)),
                ('timing',models.CharField(choices=[
                    ('immediate','هم‌زمان با رویداد'),('before','قبل از رویداد'),
                    ('after','بعد از رویداد'),
                ],default='immediate',max_length=12)),
                ('offset',models.PositiveIntegerField(default=0)),
                ('offset_unit',models.CharField(choices=[
                    ('minutes','دقیقه'),('hours','ساعت'),('days','روز'),
                ],default='minutes',max_length=10)),
                ('message_template',models.TextField(blank=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('updated_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='updated_sms_rules',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['event']},
        ),
        migrations.CreateModel(
            name='SmsScheduledMessage',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('event_key',models.CharField(db_index=True,max_length=140,unique=True)),
                ('number',models.CharField(max_length=20)),
                ('body',models.TextField()),
                ('due_at',models.DateTimeField(db_index=True)),
                ('status',models.CharField(choices=[
                    ('pending','در انتظار'),('sending','در حال ارسال'),
                    ('accepted','پذیرفته‌شده'),('failed','ناموفق'),('cancelled','لغوشده'),
                ],db_index=True,default='pending',max_length=12)),
                ('attempt_count',models.PositiveSmallIntegerField(default=0)),
                ('error',models.CharField(blank=True,max_length=300)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('rule',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='scheduled_messages',to='core.smsautomationrule')),
            ],
            options={'ordering':['due_at','id']},
        ),
        migrations.AddIndex(
            model_name='smsscheduledmessage',
            index=models.Index(fields=['status','due_at'],name='sms_queue_status_due_idx'),
        ),
    ]
