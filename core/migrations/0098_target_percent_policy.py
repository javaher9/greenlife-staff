from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0097_sales_target_bands"),
    ]
    operations = [
        migrations.CreateModel(
            name="TargetPercentPolicy",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("period_year", models.PositiveSmallIntegerField()),
                ("period_month", models.PositiveSmallIntegerField()),
                ("heavy_percent", models.DecimalField(max_digits=6, decimal_places=2, default=70)),
                ("target_one_percent", models.DecimalField(max_digits=6, decimal_places=2, default=130)),
                ("target_two_percent", models.DecimalField(max_digits=6, decimal_places=2, default=160)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("updated_by", models.ForeignKey(null=True, related_name="+", on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="targetpercentpolicy",
            constraint=models.UniqueConstraint(fields=("period_year", "period_month"), name="unique_sales_target_percent_month"),
        ),
    ]
