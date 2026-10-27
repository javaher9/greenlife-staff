from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0100_financial_staff_permissions'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeprofile',
            name='remote_attendance_enabled',
            field=models.BooleanField(
                default=False,
                help_text='مجوز فردی دورکاری: ورود و خروج از راه دور بدون GPS شعبه، با ثبت استراحت. فقط برای مشاور.',
            ),
        ),
        migrations.AddField(
            model_name='attendance',
            name='break_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='attendance',
            name='break_total_minutes',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AlterField(
            model_name='attendance',
            name='check_in_location_status',
            field=models.CharField(
                max_length=20,
                default='legacy',
                choices=[
                    ('verified','تأیید موقعیت'),('outside','خارج محدوده'),
                    ('low_accuracy','دقت پایین'),('unavailable','موقعیت ناموجود'),
                    ('manual','ثبت دستی مدیر'),('remote','دورکاری مجاز'),
                    ('legacy','قدیمی'),
                ],
            ),
        ),
        migrations.AlterField(
            model_name='visitappointment',
            name='source',
            field=models.CharField(
                max_length=20,
                default='call_center',
                choices=[
                    ('call_center','کال‌سنتر'),('receptionist','منشی'),
                    ('consultant','مشاور'),('admin','مدیریت'),
                ],
            ),
        ),
    ]
