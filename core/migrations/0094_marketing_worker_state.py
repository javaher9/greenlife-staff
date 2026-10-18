from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [("core", "0093_quality_control_role")]

    operations = [
        migrations.CreateModel(
            name="MarketingWorkerState",
            fields=[
                ("key", models.CharField(max_length=40, primary_key=True, serialize=False)),
                ("heartbeat_at", models.DateTimeField(blank=True, db_index=True, null=True)),
                ("last_run_leads", models.PositiveIntegerField(default=0)),
                ("activity", models.CharField(blank=True, max_length=180)),
                ("last_error", models.CharField(blank=True, max_length=240)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Marketing worker state",
                "verbose_name_plural": "Marketing worker states",
            },
        ),
    ]
