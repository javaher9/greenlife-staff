from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0023_consultant_finance_entry')]

    operations = [
        migrations.AddField(
            model_name='financialtransaction',
            name='receipt_original_size',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='receipt_compressed_size',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='analysis_status',
            field=models.CharField(
                choices=[
                    ('pending', 'در صف تحلیل'), ('processed', 'تحلیل‌شده'),
                    ('failed', 'خطای تحلیل'), ('skipped', 'تحلیل‌نشده'),
                ],
                default='skipped', max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='receipt_analysis',
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='analysis_error',
            field=models.CharField(blank=True, max_length=500),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='analyzed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
