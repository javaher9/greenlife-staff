from django.db import migrations, models


ROLE_CHOICES = [
    ('admin', 'مدیر سیستم'),
    ('internal_manager', 'مدیر داخلی'),
    ('manager', 'مدیر شعبه'),
    ('call_center', 'کال‌سنتر'),
    ('employee', 'کارمند'),
    ('referrer', 'معرف مشتری'),
]


class Migration(migrations.Migration):
    dependencies = [('core', '0021_alter_checklisttemplate_role')]

    operations = [
        migrations.AlterField(
            model_name='employeeprofile',
            name='role',
            field=models.CharField(choices=ROLE_CHOICES,default='employee',max_length=20),
        ),
        migrations.AlterField(
            model_name='checklisttemplate',
            name='role',
            field=models.CharField(blank=True,choices=ROLE_CHOICES,max_length=20),
        ),
    ]
