# Sales target bands: configurable tiers for each Jalali month.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0096_diet_companion_tracking"),
    ]
    operations = [
        migrations.CreateModel(
            name="SalesTargetBand",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("key", models.CharField(max_length=96, unique=True)),
                ("period_year", models.PositiveSmallIntegerField()),
                ("period_month", models.PositiveSmallIntegerField()),
                ("scope", models.CharField(max_length=16, choices=[
                    ("overall", "کل فروش"), ("branch", "مرکز"), ("call_center", "بیعانه کال‌سنتر"),
                    ("flower", "گل کال‌سنتر"), ("consultant", "مشاور"),
                ])),
                ("heavy_limit", models.DecimalField(decimal_places=2, max_digits=14)),
                ("sales_floor", models.DecimalField(decimal_places=2, max_digits=14)),
                ("target_one", models.DecimalField(decimal_places=2, max_digits=14)),
                ("target_two", models.DecimalField(decimal_places=2, max_digits=14)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to="core.branch")),
                ("employee", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
                ("updated_by", models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name="+", to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["scope", "key"]},
        ),
        migrations.AddIndex(
            model_name="salestargetband",
            index=models.Index(fields=["period_year", "period_month", "scope"], name="core_sales_p_y_m_scope_idx"),
        ),
    ]
