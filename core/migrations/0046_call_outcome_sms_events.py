from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[('core','0045_website_lead_integration_settings')]

    operations=[
        migrations.AlterField(
            model_name='smsautomationrule',
            name='event',
            field=models.CharField(
                max_length=50,unique=True,choices=[
                    ('appointment_booked','ثبت نوبت'),
                    ('appointment_reminder','یادآوری نوبت'),
                    ('appointment_changed','تغییر نوبت'),
                    ('appointment_cancelled','لغو نوبت'),
                    ('patient_arrived','مراجعه بیمار'),
                    ('payment_approved','تأیید پرداخت'),
                    ('payment_due','یادآوری پرداخت'),
                    ('device_session_booked','رزرو جلسه دستگاه'),
                    ('device_session_reminder','یادآوری جلسه دستگاه'),
                    ('device_session_started','شروع جلسه دستگاه'),
                    ('device_session_finished','پایان جلسه دستگاه'),
                    ('treatment_followup','پیگیری پس از درمان'),
                    ('lead_new','لید جدید'),
                    ('lead_overdue','تأخیر در تماس با لید'),
                    ('call_no_answer','نتیجه تماس ← پاسخ نداد'),
                    ('call_not_interested','نتیجه تماس ← تمایل ندارد'),
                    ('call_follow_up','نتیجه تماس ← نیاز به پیگیری'),
                    ('call_appointment','نتیجه تماس ← نوبت داده شد'),
                    ('staff_late','تأخیر حضور پرسنل'),
                    ('staff_task_due','سررسید وظیفه'),
                    ('internal_approval','مصوبه یا تأیید مدیریتی'),
                ],
            ),
        ),
    ]
