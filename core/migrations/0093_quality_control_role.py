from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0092_call_center_routing_day')]

    operations = [
        migrations.AlterField(
            model_name='employeeprofile',
            name='role',
            field=models.CharField(
                max_length=20,
                default='employee',
                choices=[
                    ('admin', 'مدیر سیستم'),
                    ('internal_manager', 'مدیر داخلی'),
                    ('manager', 'مدیر شعبه'),
                    ('quality_control', 'کنترل کیفیت'),
                    ('referral_supervisor', 'ناظر شبکه فروش'),
                    ('call_center', 'کال‌سنتر'),
                    ('consultant', 'مشاور'),
                    ('doctor', 'پزشک'),
                    ('receptionist', 'منشی'),
                    ('employee', 'کارمند'),
                    ('referrer', 'معرف مشتری'),
                ],
            ),
        ),
    ]
