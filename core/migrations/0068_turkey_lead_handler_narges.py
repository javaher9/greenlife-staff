from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[
        ('core','0067_sales_network_permission_and_rad_cleanup'),
    ]

    operations=[
        migrations.AddField(
            model_name='employeeprofile',
            name='handles_turkey_leads',
            field=models.BooleanField(
                default=False,
                help_text='این کاربر مقصد اختصاصی لیدهای Türkiye است.',
            ),
        ),
    ]
