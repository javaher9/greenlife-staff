from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0020_internal_manager_role')]

    operations = [
        migrations.AlterField(
            model_name='checklisttemplate',
            name='role',
            field=models.CharField(
                blank=True,
                choices=[
                    ('admin', 'مدیر سیستم'),
                    ('internal_manager', 'مدیر داخلی'),
                    ('manager', 'مدیر شعبه'),
                    ('employee', 'کارمند'),
                    ('referrer', 'معرف مشتری'),
                ],
                max_length=20,
            ),
        ),
    ]
