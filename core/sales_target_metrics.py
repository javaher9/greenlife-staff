"""Monthly sales measures shared by the executive sales views and channel atlas."""
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from django.db.models import Q, Sum
from django.db.models.functions import Coalesce

from .jalali import jalali_to_gregorian
from .models import Branch, FinancialTransaction
from .sales_target_models import SalesTargetBand, TargetPercentPolicy


def jalali_month_dates(year, month):
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    return date(*jalali_to_gregorian(year, month, 1)), date(*jalali_to_gregorian(next_year, next_month, 1))


def active_sales_branches():
    return (Branch.objects.filter(is_active=True)
            .filter(Q(country__code="IR") | Q(country__isnull=True))
            .exclude(name__icontains="ارومیه").exclude(name__icontains="افسریه").order_by("name"))


def monthly_policy(year, month):
    configuration = TargetPercentPolicy.objects.filter(period_year=year, period_month=month).first()
    return configuration or TargetPercentPolicy(period_year=year, period_month=month)


def monthly_plans(policy):
    """Recompute every boundary when the policy changes, including previously saved floors."""
    year, month = policy.period_year, policy.period_month
    prefix = f"{year}-{month:02d}:"
    plans = {}
    for key, sales_floor in SalesTargetBand.objects.filter(
        period_year=year, period_month=month,
    ).values_list("key", "sales_floor"):
        heavy, floor, one, two = policy.bands(sales_floor)
        plans[key.removeprefix(prefix)] = SimpleNamespace(
            heavy_limit=heavy, sales_floor=floor, target_one=one, target_two=two,
        )
    return plans


def approved_sales(start, end):
    # CRM imports can mirror the same receipt. Only approved manual income counts.
    return FinancialTransaction.objects.filter(
        source="manual", entry_type="inc", review_status="approved",
        occurred_at__gte=start, occurred_at__lt=end,
    )


def million_toman(rials):
    return ((rials or Decimal("0")) / Decimal("10000000")).quantize(Decimal("0.01"))


def sales_by_branch_and_flower(income):
    by_branch = {key: million_toman(value) for key, value in income.order_by()
                 .values("branch_id").annotate(sales=Sum("amount")).values_list("branch_id", "sales")}
    owners = income.annotate(flower_id=Coalesce(
        "call_center_owner_id", "appointment__lead__first_appointment_by_id",
    )).filter(flower_id__isnull=False)
    by_flower = {key: million_toman(value) for key, value in owners.order_by()
                 .values("flower_id").annotate(sales=Sum("amount")).values_list("flower_id", "sales")}
    return by_branch, by_flower
