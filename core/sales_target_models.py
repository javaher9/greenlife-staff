"""Sales target bands for executive target dashboard, values in million toman."""
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class SalesTargetBand(models.Model):
    """One configuration per subject and Jalali month, without nullable unique keys."""
    SCOPES = [
        ("overall", "کل فروش"),
        ("branch", "مرکز"),
        ("call_center", "بیعانه کال‌سنتر"),
        ("flower", "گل کال‌سنتر"),
        ("consultant", "مشاور"),
    ]
    key = models.CharField(max_length=96, unique=True)
    period_year = models.PositiveSmallIntegerField()
    period_month = models.PositiveSmallIntegerField()
    scope = models.CharField(max_length=16, choices=SCOPES)
    branch = models.ForeignKey("core.Branch", on_delete=models.CASCADE, null=True, blank=True)
    employee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, null=True, blank=True)
    heavy_limit = models.DecimalField(max_digits=14, decimal_places=2)
    sales_floor = models.DecimalField(max_digits=14, decimal_places=2)
    target_one = models.DecimalField(max_digits=14, decimal_places=2)
    target_two = models.DecimalField(max_digits=14, decimal_places=2)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")
    class Meta:
        ordering = ["scope", "key"]
        indexes = [models.Index(fields=["period_year", "period_month", "scope"])]

    def clean(self):
        super().clean()
        values = (self.heavy_limit, self.sales_floor, self.target_one, self.target_two)
        if any(v is None for v in values) or not (Decimal("0") < values[0] < values[1] < values[2] < values[3]):
            raise ValidationError("مقادیر باید به‌ترتیب صعودی و بزرگ‌تر از صفر باشند: پایان جریمه سنگین، کف فروش، تارگت ۱، تارگت ۲.")
        if not 1 <= self.period_month <= 12:
            raise ValidationError("ماه شمسی باید بین ۱ و ۱۲ باشد.")

    def __str__(self):
        return f"{self.key}: {self.sales_floor} / {self.target_one} / {self.target_two}"

class TargetPercentPolicy(models.Model):
    """Global monthly percentages of the sales floor, shared across all sales scopes."""
    period_year = models.PositiveSmallIntegerField()
    period_month = models.PositiveSmallIntegerField()
    heavy_percent = models.DecimalField(max_digits=6, decimal_places=2, default=70)
    target_one_percent = models.DecimalField(max_digits=6, decimal_places=2, default=130)
    target_two_percent = models.DecimalField(max_digits=6, decimal_places=2, default=160)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["period_year", "period_month"], name="unique_sales_target_percent_month")]

    def clean(self):
        super().clean()
        p = (self.heavy_percent, self.target_one_percent, self.target_two_percent)
        if any(x is None or not x.is_finite() for x in p) or not (Decimal("0") < p[0] < Decimal("100") < p[1] < p[2] <= Decimal("1000")):
            raise ValidationError("درصدها باید این ترتیب را داشته باشند: ۰ < پایان جریمه سنگین < ۱۰۰ < تارگت ۱ < تارگت ۲ (حداکثر ۱۰۰۰).")

    def bands(self, floor):
        """Return monetary boundaries in millions; recomputed from the current policy."""
        return (
            (floor * self.heavy_percent / Decimal("100")).quantize(Decimal("0.01")),
            floor,
            (floor * self.target_one_percent / Decimal("100")).quantize(Decimal("0.01")),
            (floor * self.target_two_percent / Decimal("100")).quantize(Decimal("0.01")),
        )
