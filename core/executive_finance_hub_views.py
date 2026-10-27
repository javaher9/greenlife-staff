"""Executive-only, read-only financial snapshot from approved local transactions.

Figures are *recorded transactions*, not audited profit, bank cash or commitments.
No writes, migrations, remote API or AI calls are performed.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q, Sum
from django.db.models.functions import Coalesce
from django.db.models.functions import TruncDate
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from .jalali import gregorian_to_jalali, jalali_to_gregorian
from .models import FinancialTransaction
from django.contrib.auth.models import User
from .call_center_identity import call_center_display_name

MILLION_TOMAN_RIALS = Decimal("10000000")


def million_toman(value):
    if value is None:
        return None
    return round(Decimal(value) / MILLION_TOMAN_RIALS, 2)


def local_boundary(day):
    return timezone.make_aware(datetime.combine(day, time.min), timezone.get_current_timezone())


@never_cache
@login_required
def executive_finance_hub(request):
    if (request.user.username or "").lower() not in settings.EXECUTIVE_USERNAMES:
        raise PermissionDenied("Executive finance access denied.")

    today = timezone.localdate()
    jy, jm, _ = gregorian_to_jalali(today.year, today.month, today.day)
    first = datetime(*jalali_to_gregorian(jy, jm, 1)).date()
    next_jy, next_jm = (jy + 1, 1) if jm == 12 else (jy, jm + 1)
    last_exclusive = datetime(*jalali_to_gregorian(next_jy, next_jm, 1)).date()
    start, end = local_boundary(first), local_boundary(last_exclusive)
    today_start, tomorrow_start = local_boundary(today), local_boundary(today + timedelta(days=1))

    # Explicit scope: Iranian company records only. Exclude unassigned/foreign
    # branches rather than silently mixing TRY and IRR in a Toman summary.
    approved = FinancialTransaction.objects.filter(
        review_status="approved", branch__country__code="IR"
    )
    month = approved.filter(occurred_at__gte=start, occurred_at__lt=end)
    day = approved.filter(occurred_at__gte=today_start, occurred_at__lt=tomorrow_start)
    pending = FinancialTransaction.objects.filter(
        review_status="pending", branch__country__code="IR"
    )

    def totals(queryset):
        result = queryset.aggregate(
            income=Sum("amount", filter=Q(entry_type="inc")),
            expense=Sum("amount", filter=Q(entry_type="exp")),
            count=Count("id"),
        )
        return {
            "income": million_toman(result["income"]),
            "expense": million_toman(result["expense"]),
            "count": result["count"],
        }

    mt = totals(month)
    dt = totals(day)
    # Difference of recorded receipts and expenses, NOT accounting net profit.
    net = (mt["income"] - mt["expense"]) if mt["income"] is not None and mt["expense"] is not None else None
    pending_count = pending.count()
    month_count = mt["count"]

    branches = list(
        month.values("branch__name").annotate(
            income=Sum("amount", filter=Q(entry_type="inc")),
            expense=Sum("amount", filter=Q(entry_type="exp")),
        ).order_by("-income")[:8]
    )
    for item in branches:
        item["income_m"] = million_toman(item["income"])
        item["expense_m"] = million_toman(item["expense"])
        item["name"] = item["branch__name"] or "بدون نام"

    category_rows = list(
        month.filter(entry_type="exp").values("account_heading").annotate(
            total=Sum("amount"), count=Count("id")
        ).order_by("-total")[:7]
    )
    for item in category_rows:
        item["name"] = item["account_heading"] or "دسته‌بندی‌نشده"
        item["amount_m"] = million_toman(item["total"])

    daily = list(
        month.annotate(day=TruncDate("occurred_at", tzinfo=timezone.get_current_timezone()))
        .values("day").annotate(
            income=Sum("amount", filter=Q(entry_type="inc")),
            expense=Sum("amount", filter=Q(entry_type="exp")),
        ).order_by("day")
    )
    maximum = max(
        [abs(Decimal(row[field] or 0)) for row in daily for field in ("income", "expense")] or [Decimal("1")]
    ) or Decimal("1")
    for row in daily:
        row["label"] = str(gregorian_to_jalali(row["day"].year, row["day"].month, row["day"].day)[2])
        row["income_height"] = round(max(Decimal("0"), Decimal(row["income"] or 0)) / maximum * 100, 1)
        row["expense_height"] = round(max(Decimal("0"), Decimal(row["expense"] or 0)) / maximum * 100, 1)
        row["income_m"] = million_toman(row["income"])
        row["expense_m"] = million_toman(row["expense"])

    # Call-center is a breakdown of approved income, never extra revenue.
    call_center_income = month.filter(entry_type="inc").filter(
        Q(call_center_owner__profile__role="call_center")
        | Q(
            call_center_owner__isnull=True,
            appointment__lead__first_appointment_by__profile__role="call_center",
        )
    )
    call_center_total_rial = (
        call_center_income.aggregate(v=Sum("amount"))["v"] or Decimal("0")
    )
    flower_rows = list(
        call_center_income.annotate(
            flower_id=Coalesce(
                "call_center_owner_id", "appointment__lead__first_appointment_by_id",
            )
        ).values("flower_id")
        .annotate(amount=Sum("amount"), count=Count("pk"))
        .order_by("-amount")
    )
    flowers_by_id = User.objects.in_bulk([
        row["flower_id"] for row in flower_rows if row["flower_id"]
    ])
    largest = max(
        (Decimal(row["amount"] or 0) for row in flower_rows),
        default=Decimal("1"),
    ) or Decimal("1")
    for item in flower_rows:
        member = flowers_by_id.get(item["flower_id"])
        item["flower"] = (
            call_center_display_name(member) if member else "گل تعیین‌نشده"
        )
        item["amount_m"] = million_toman(item["amount"])
        item["height"] = round(Decimal(item["amount"] or 0) / largest * 100, 1)
        item["percent"] = (
            round(Decimal(item["amount"] or 0) / call_center_total_rial * 100, 1)
            if call_center_total_rial else 0
        )
    approved_deposits = month.filter(
        entry_type="inc", source="manual",
        raw_data__payment_kind="call_center_deposit",
    )
    pending_deposits = pending.filter(
        entry_type="inc", source="manual",
        raw_data__payment_kind="call_center_deposit",
    )
    pending_deposit_rial = (
        pending_deposits.aggregate(v=Sum("amount"))["v"] or Decimal("0")
    )

    return render(request, "core/executive_finance_hub.html", {
        "month_title": f"{jy}/{jm:02d}",
        "month_count": month_count,
        "today_count": dt["count"],
        "today_income": dt["income"],
        "month_income": mt["income"],
        "month_expense": mt["expense"],
        "recorded_difference": net,
        "pending_count": pending_count,
        "branches": branches,
        "categories": category_rows,
        "daily": daily,
        "call_center_total": million_toman(call_center_total_rial),
        "call_center_flowers": flower_rows,
        "deposit_approved_amount": million_toman(
            approved_deposits.aggregate(v=Sum("amount"))["v"] or Decimal("0")
        ),
        "deposit_approved_count": approved_deposits.count(),
        "deposit_pending_amount": million_toman(pending_deposit_rial),
        "deposit_pending_count": pending_deposits.count(),
    })
