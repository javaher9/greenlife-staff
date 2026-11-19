"""Sales attainment for the executive channel room, based on the current Tehran month."""
from datetime import datetime, time
from decimal import Decimal, ROUND_DOWN
from zoneinfo import ZoneInfo

from .call_center_identity import call_center_display_name
from .jalali import gregorian_to_jalali
from .models import EmployeeProfile
from .sales_target_metrics import (
    active_sales_branches, approved_sales, jalali_month_dates, monthly_plans,
    monthly_policy, sales_by_branch_and_flower,
)


def _vessel(key, name, actual, plan):
    one = plan.target_one if plan and plan.target_one and plan.target_one > 0 else None
    two = plan.target_two if plan and plan.target_two and plan.target_two > 0 else None
    # Leave the same overachievement headroom as the personal monthly sales gauge.
    ceiling = max(one or 0, two or 0) * Decimal("1.20")

    def attainment(target):
        if actual is None or target is None:
            return None
        return (100 * actual / target).quantize(Decimal("0.1"), rounding=ROUND_DOWN)

    def level(value):
        if value is None or not ceiling:
            return None
        return round(min(100, max(0, 100 * value / ceiling)), 3)

    availability = ""
    if actual is None:
        availability = "فروش در دسترس نیست"
    elif one is None and two is None:
        availability = "تارگت تنظیم نشده"
    elif one is None:
        availability = "تارگت 1 تنظیم نشده"
    elif two is None:
        availability = "تارگت 2 تنظیم نشده"

    return {
        "key": key, "name": name, "availability": availability,
        "actual_display": f"{actual:,.2f}".rstrip("0").rstrip(".") if actual is not None else None,
        "t1_percent": attainment(one), "t2_percent": attainment(two),
        "level": level(actual), "t1_level": level(one), "t2_level": level(two),
        "reading": ":".join(format(v, ".2f") if v is not None else "" for v in (actual, one, two)),
    }


def target_context(now):
    tehran = ZoneInfo("Asia/Tehran")
    today = now.astimezone(tehran).date()
    year, month, _ = gregorian_to_jalali(today.year, today.month, today.day)
    start_date, end_date = jalali_month_dates(year, month)
    income = approved_sales(
        datetime.combine(start_date, time.min, tzinfo=tehran),
        datetime.combine(end_date, time.min, tzinfo=tehran),
    )
    plans = monthly_plans(monthly_policy(year, month))
    by_branch, by_flower = sales_by_branch_and_flower(income)
    flowers = (EmployeeProfile.objects.filter(is_active=True, user__is_active=True, role="call_center")
               .select_related("user").order_by("user__first_name", "user__last_name", "user__username"))

    def row(scope, identifier, label, sales):
        key = f"{scope}:{identifier}"
        return _vessel(key, label, sales.get(identifier, Decimal(0)), plans.get(key))

    return {
        "target_period": f"{year}/{month:02d}",
        "target_departments": [
            {"key": "call_center", "title": "تارگت گل‌های کال‌سنتر",
             "vessels": [row("flower", p.user_id, call_center_display_name(p.user), by_flower) for p in flowers]},
            {"key": "centers", "title": "تارگت فروش مراکز",
             "vessels": [row("branch", pk, name, by_branch)
                         for pk, name in active_sales_branches().values_list("pk", "name")]},
        ],
    }
