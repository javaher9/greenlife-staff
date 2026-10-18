from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("core", "0094_marketing_worker_state")]

    operations = [
        migrations.CreateModel(
            name="MarketingSmsPlan",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("day", models.DateField(unique=True)),
                ("segment_key", models.CharField(max_length=64)),
                ("segment_title", models.CharField(max_length=100)),
                ("body", models.TextField(max_length=600)),
                ("rationale", models.CharField(max_length=250)),
                ("candidate_count", models.PositiveIntegerField(blank=True, null=True)),
                ("preview_limited", models.BooleanField(default=False)),
                ("status", models.CharField(default="proposal", max_length=20)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={"ordering": ["-day"], "verbose_name": "Daily SMS strategy proposal"},
        ),
    ]
