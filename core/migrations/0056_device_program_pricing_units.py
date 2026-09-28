from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('core','0055_device_booking')]
    operations=[
        migrations.AddField(
            model_name='patientdeviceprogram',
            name='units_per_session',
            field=models.PositiveSmallIntegerField(default=1),
        ),
    ]
