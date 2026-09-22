from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0046_lead_assigned_at_and_pending_backfill'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='referrallead',
            index=models.Index(fields=['assigned_at'], name='reflead_assigned_at_idx'),
        ),
    ]
