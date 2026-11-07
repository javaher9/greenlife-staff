"""Infrastructure inventory and manual balance verification.

Never store passwords, one-time codes, recovery tokens, or full MFA secrets here.
"""
from django.conf import settings
from django.db import models


class InfrastructureService(models.Model):
    KIND_CHOICES = [
        ("internet", "اینترنت"),
        ("telephone", "تلفن و شماره پنج‌رقمی"),
        ("pbx", "سانترال و VoIP"),
        ("hosting", "هاست و دامنه"),
        ("other", "سایر"),
    ]
    branch = models.ForeignKey(
        "core.Branch", on_delete=models.PROTECT, null=True, blank=True,
        related_name="infrastructure_services",
    )
    kind = models.CharField(max_length=20, choices=KIND_CHOICES)
    label = models.CharField(max_length=150)
    provider = models.CharField(max_length=120)
    account_reference = models.CharField(
        max_length=120, blank=True,
        help_text="فقط شناسه عمومی اشتراک؛ رمز، OTP یا اطلاعات بازیابی وارد نشود.",
    )
    portal_url = models.URLField(blank=True)
    registered_owner = models.CharField(max_length=150, blank=True)
    verification_contact_hint = models.CharField(
        max_length=80, blank=True,
        help_text="مثلاً «شماره مدیر شرکت، پایان 1234»؛ شماره کامل یا کد تأیید وارد نشود.",
    )
    company_controls_recovery = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["branch__name", "kind", "label"]

    def __str__(self):
        return self.label


class InfrastructureBalanceCheck(models.Model):
    STATUS_CHOICES = [
        ("unknown", "نامشخص / نیازمند استعلام"),
        ("clear", "بدون بدهی (طبق بررسی)"),
        ("owed", "بدهی گزارش شده"),
    ]
    SOURCE_CHOICES = [
        ("portal", "پنل رسمی ارائه‌دهنده"),
        ("bill", "قبض یا فاکتور"),
        ("provider", "پاسخ پشتیبانی شرکت"),
        ("other", "سایر"),
    ]
    service = models.ForeignKey(
        InfrastructureService, on_delete=models.PROTECT, related_name="balance_checks",
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="unknown")
    amount_due = models.DecimalField(
        max_digits=17, decimal_places=0, null=True, blank=True,
        help_text="مبلغ به ریال؛ فقط در صورت مشاهده سند معتبر.",
    )
    due_date = models.DateField(null=True, blank=True)
    source = models.CharField(max_length=15, choices=SOURCE_CHOICES)
    note = models.TextField(blank=True)
    checked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="infrastructure_checks",
    )
    checked_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-checked_at", "-pk"]

    def __str__(self):
        return f"{self.service} — {self.get_status_display()}"
