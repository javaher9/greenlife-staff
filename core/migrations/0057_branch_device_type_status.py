from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0046_call_outcome_sms_events'),
    ]

    operations = [
        migrations.CreateModel(
            name='BranchDeviceTypeStatus',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('is_active', models.BooleanField(default=True)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='device_type_statuses', to='core.branch')),
                ('device_type', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='branch_statuses', to='core.devicetypeschedule')),
            ],
            options={
                'ordering': ['branch_id', 'device_type_id'],
            },
        ),
        migrations.AddConstraint(
            model_name='branchdevicetypestatus',
            constraint=models.UniqueConstraint(fields=('branch', 'device_type'), name='uniq_branch_device_type_status'),
        ),
    ]
