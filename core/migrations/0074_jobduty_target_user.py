from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0073_rebalance_recent_banafsha_leads"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobdutytemplate",
            name="target_user",
            field=models.ForeignKey(
                blank=True,
                help_text="اگر انتخاب شود، این شرح وظایف فقط برای همین پرسنل نمایش داده می‌شود.",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="assigned_job_duties",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
    ]
