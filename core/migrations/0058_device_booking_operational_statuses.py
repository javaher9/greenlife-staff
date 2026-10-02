from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0057_branch_device_type_status'),
    ]

    operations = [
        migrations.AlterField(
            model_name='devicesessionbooking',
            name='status',
            field=models.CharField(
                choices=[
                    ('booked', 'رزرو شده'),
                    ('arrived', 'حاضر شد'),
                    ('late', 'دیر رسید'),
                    ('completed', 'انجام شد'),
                    ('no_show', 'نیامد'),
                    ('cancelled', 'لغو شده'),
                    ('rescheduled', 'جابجا شد'),
                ],
                db_index=True,
                default='booked',
                max_length=12,
            ),
        ),
    ]
