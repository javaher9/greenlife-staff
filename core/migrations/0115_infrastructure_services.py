from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def create_auditor_group(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="GreenLife Infrastructure Audit")


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0114_bulk_sms_automations"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations = [
        migrations.CreateModel(
            name="InfrastructureService",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("kind", models.CharField(choices=[("internet", "اینترنت"), ("telephone", "تلفن و شماره پنج‌رقمی"), ("pbx", "سانترال و VoIP"), ("hosting", "هاست و دامنه"), ("other", "سایر")], max_length=20)),
                ("label", models.CharField(max_length=150)),
                ("provider", models.CharField(max_length=120)),
                ("account_reference", models.CharField(blank=True, help_text="فقط شناسه عمومی اشتراک؛ رمز، OTP یا اطلاعات بازیابی وارد نشود.", max_length=120)),
                ("portal_url", models.URLField(blank=True)),
                ("registered_owner", models.CharField(blank=True, max_length=150)),
                ("verification_contact_hint", models.CharField(blank=True, help_text="مثلاً «شماره مدیر شرکت، پایان 1234»؛ شماره کامل یا کد تأیید وارد نشود.", max_length=80)),
                ("company_controls_recovery", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("branch", models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="infrastructure_services", to="core.branch")),
            ],
            options={"ordering": ["branch__name", "kind", "label"]},
        ),
        migrations.CreateModel(
            name="InfrastructureBalanceCheck",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("status", models.CharField(choices=[("unknown", "نامشخص / نیازمند استعلام"), ("clear", "بدون بدهی (طبق بررسی)"), ("owed", "بدهی گزارش شده")], default="unknown", max_length=12)),
                ("amount_due", models.DecimalField(blank=True, decimal_places=0, help_text="مبلغ به ریال؛ فقط در صورت مشاهده سند معتبر.", max_digits=17, null=True)),
                ("due_date", models.DateField(blank=True, null=True)),
                ("source", models.CharField(choices=[("portal", "پنل رسمی ارائه‌دهنده"), ("bill", "قبض یا فاکتور"), ("provider", "پاسخ پشتیبانی شرکت"), ("other", "سایر")], max_length=15)),
                ("note", models.TextField(blank=True)),
                ("checked_at", models.DateTimeField(auto_now_add=True)),
                ("checked_by", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="infrastructure_checks", to=settings.AUTH_USER_MODEL)),
                ("service", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="balance_checks", to="core.infrastructureservice")),
            ],
            options={"ordering": ["-checked_at", "-pk"]},
        ),
        migrations.RunPython(create_auditor_group, reverse_code=migrations.RunPython.noop),
    ]
