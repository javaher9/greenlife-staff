from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0064_add_istanbul_branch'),
    ]

    operations = [
        migrations.AddField(
            model_name='employeeprofile',
            name='can_register_instagram_dm_lead',
            field=models.BooleanField(
                default=False,
                help_text='اجازه ثبت دستی لیدهایی که شماره‌شان از دایرکت اینستاگرام دریافت شده است.',
            ),
        ),
    ]
