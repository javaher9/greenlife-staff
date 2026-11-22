"""Read-only two-month financial comparison for the existing Finance page.

Uses the same approved FinancialTransaction receipts as /finance/.
All grouping is derived from those rows; no sync, mutations or AI/network calls.
"""
from datetime import datetime, time, timedelta
from decimal import Decimal
import re

from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Case, CharField, Count, F, Q, Sum, Value, When
from django.db.models.functions import Coalesce, TruncDate
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.cache import never_cache

from .call_center_identity import call_center_display_name
from .jalali import gregorian_to_jalali, jalali_to_gregorian
from .models import Branch, EmployeeProfile, FinancialTransaction, ReferralLead
from .templatetags.finance_intelligence import (
    DEPOSIT_KIND, _apply_transaction_filters, _finance_branch_name,
)
from .views import finance_required, role_of

ZERO = Decimal("0")
MILLION_TOMAN_RIALS = Decimal("10000000")
PERSIAN_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def _previous_month(year, month):
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _month_key(year, month):
    return f"{year:04d}/{month:02d}"


def _parse_month(raw):
    normalized = str(raw or "").strip().translate(PERSIAN_DIGITS)
    match = re.fullmatch(r"(1[34]\d{2})[/\-](0?[1-9]|1[0-2])", normalized)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def _month_bounds(year, month):
    next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
    first = datetime(*jalali_to_gregorian(year, month, 1)).date()
    next_first = datetime(*jalali_to_gregorian(next_year, next_month, 1)).date()
    tz = timezone.get_current_timezone()
    start = timezone.make_aware(datetime.combine(first, time.min), tz)
    end = timezone.make_aware(datetime.combine(next_first, time.min), tz)
    return start, end, (next_first - first).days


def _money(value):
    return value if value is not None else ZERO


def _millions(value):
    return round(_money(value) / MILLION_TOMAN_RIALS, 2)


def _percentage_delta(before, after):
    if not before:
        return None
    return round((after - before) * 100 / before, 1)


def _payment_label(raw):
    label = " ".join(str(raw or "").split())
    if not label:
        return "روش نامشخص"
    normalized = " ".join(label.upper().replace("-", " ").replace("_", " ").split())
    aliases = {
        "POS H": "POS-H", "POS S": "POS-S",
        "CC G": "CC-G", "CC S": "CC-S",
        "CC P": "CC-P", "CC D": "CC-D",
        "LINK": "لینک پرداخت", "CASH": "نقدی",
        "BANK TRANSFER": "حواله بانکی",
        "TRANSFER": "کارت‌به‌کارت / حواله",
    }
    if normalized in aliases:
        return aliases[normalized]
    if normalized == "CCG":
        return "CC-G"
    if normalized == "CCS":
        return "CC-S"
    return label


def _group(queryset, field, labeler):
    rows = queryset.values(field).annotate(total=Sum("amount"), count=Count("pk"))
    result = {}
    for entry in rows:
        name = labeler(entry.get(field))
        record = result.setdefault(name, {"total": ZERO, "count": 0})
        record["total"] += _money(entry["total"])
        record["count"] += entry["count"]
    return result


def _breakdown(queryset, kind):
    if kind == "payments":
        return _group(queryset, "payment_method", _payment_label)
    if kind == "branches":
        qs = queryset.annotate(report_branch=_finance_branch_name())
        return _group(qs, "report_branch", lambda value: value or "بدون شعبه")
    if kind == "services":
        labels = dict(FinancialTransaction.SALE_REASON)
        # Legacy blank categories remain explicit rather than silently reclassifying receipts.
        return _group(queryset, "sale_reason", lambda value: labels.get(value, value) if value else "دسته‌بندی‌نشده")
    if kind == "sources":
        qs = queryset.annotate(
            lead_source=Case(
                When(appointment__isnull=True, then=Value("direct")),
                default=F("appointment__lead__source"), output_field=CharField(),
            )
        )
        labels = dict(ReferralLead.SOURCE)
        labels["direct"] = "مراجعه مستقیم"
        return _group(qs, "lead_source", lambda value: labels.get(value, value) if value else "منشأ نامشخص")
    if kind == "flowers":
        qs = queryset.exclude(sale_reason="skin_care").filter(
            Q(call_center_owner__profile__role="call_center")
            | Q(call_center_owner__isnull=True, appointment__lead__first_appointment_by__profile__role="call_center")
        ).annotate(
            flower_id=Coalesce("call_center_owner_id", "appointment__lead__first_appointment_by_id")
        )
        grouped = list(qs.values("flower_id").annotate(total=Sum("amount"), count=Count("pk")))
        user_map = User.objects.in_bulk([row["flower_id"] for row in grouped if row["flower_id"]])
        result = {}
        for row in grouped:
            user = user_map.get(row["flower_id"])
            label = call_center_display_name(user) if user else "گل نامشخص"
            entry = result.setdefault(label, {"total": ZERO, "count": 0})
            entry["total"] += _money(row["total"])
            entry["count"] += row["count"]
        return result
    raise ValueError("Unknown financial dimension")


def _comparison_rows(previous, current, prev_total, curr_total):
    result = []
    for name in set(previous) | set(current):
        a = previous.get(name, {"total": ZERO, "count": 0})
        b = current.get(name, {"total": ZERO, "count": 0})
        before, after = a["total"], b["total"]
        delta = after - before
        result.append({
            "name": name, "a": _millions(before), "b": _millions(after),
            "delta": _millions(delta), "delta_pct": _percentage_delta(before, after),
            "count_a": a["count"], "count_b": b["count"],
            "share_a": round(before * 100 / prev_total, 1) if prev_total else ZERO,
            "share_b": round(after * 100 / curr_total, 1) if curr_total else ZERO,
            "share_shift": round(after * 100 / curr_total - before * 100 / prev_total, 1)
            if prev_total and curr_total else None,
        })
    result.sort(key=lambda item: (-max(abs(item["a"]), abs(item["b"])), item["name"]))
    max_value = max((max(item["a"], item["b"]) for item in result), default=ZERO) or Decimal("1")
    for row in result:
        row["bar_a"] = round(max(row["a"], ZERO) * 100 / max_value, 1)
        row["bar_b"] = round(max(row["b"], ZERO) * 100 / max_value, 1)
    return result


def _month_snapshot(base, pending_base, year, month):
    start, end, total_days = _month_bounds(year, month)
    receipts = base.filter(occurred_at__gte=start, occurred_at__lt=end)
    waiting = pending_base.filter(occurred_at__gte=start, occurred_at__lt=end)
    aggregated = receipts.aggregate(total=Sum("amount"), count=Count("pk"))
    total = _money(aggregated["total"])
    count = aggregated["count"]
    pending = waiting.aggregate(total=Sum("amount"), count=Count("pk"))
    grouped_days = receipts.annotate(
        recorded_day=TruncDate("occurred_at", tzinfo=timezone.get_current_timezone())
    ).values("recorded_day").annotate(
        total=Sum("amount"), count=Count("pk")
    )
    days = {}
    for item in grouped_days:
        day = item["recorded_day"]
        day_year, day_month, day_of_month = gregorian_to_jalali(day.year, day.month, day.day)
        if (day_year, day_month) == (year, month):
            days[day_of_month] = {
                "total": _money(item["total"]), "count": item["count"]
            }
    return {
        "key": _month_key(year, month),
        "total": total,
        "total_m": _millions(total),
        "count": count,
        "average_m": _millions(total / count) if count else ZERO,
        "pending_m": _millions(pending["total"]),
        "pending_count": pending["count"],
        "number_of_days": total_days,
        "days": days,
        "parts": {kind: _breakdown(receipts, kind) for kind in ("payments", "branches", "services", "sources", "flowers")},
    }


def _insights(first, second, comparisons, *, incomplete):
    insights = []
    delta = second["total"] - first["total"]
    if incomplete:
        insights.append("ماه جاری هنوز کامل نشده است؛ تفاوت مبلغ کل را نباید معادل رشد یا افت یک ماه کامل دانست.")
    elif first["total"]:
        direction = "افزایش" if delta > ZERO else "کاهش" if delta < ZERO else "بدون تغییر"
        insights.append(
            f"درآمد تأییدشده دوره دوم {direction} داشته است؛ اختلاف: "
            f"{_millions(abs(delta)):,} میلیون تومان ({abs(_percentage_delta(first['total'], second['total']))}٪)."
        )
    elif second["total"]:
        insights.append("در دوره اول درآمد تأییدشده‌ای ثبت نشده؛ درصد رشد از مبنای صفر قابل محاسبه نیست.")
    else:
        insights.append("برای این دو دوره، دریافت تأییدشده‌ای در داده‌های موجود پیدا نشد.")
    for kind, title in (("payments", "روش پرداخت"), ("branches", "شعبه"), ("services", "نوع خدمت")):
        rows = comparisons[kind]
        if rows:
            standout = max(rows, key=lambda row: abs(row["delta"]))
            if standout["delta"]:
                direction = "بیشتر" if standout["delta"] > 0 else "کمتر"
                insights.append(
                    f"بزرگ‌ترین تغییر مبلغ در {title} «{standout['name']}» است: "
                    f"{_millions(abs(standout['delta']) * MILLION_TOMAN_RIALS):,} میلیون تومان {direction}."
                )
    if first["pending_count"] or second["pending_count"]:
        insights.append("اسناد در انتظار تأیید از درآمد قطعی جدا شده‌اند و در جمع کل یا نمودار پرداخت‌ها محاسبه نشده‌اند.")
    return insights[:5]


@never_cache
@finance_required
def finance_month_comparison(request):
    """Owner/admin and branch manager get the same scopes as the Finance screen."""
    today = timezone.localdate()
    current_year, current_month, _ = gregorian_to_jalali(today.year, today.month, today.day)
    last_year, last_month = _previous_month(current_year, current_month)
    prior_year, prior_month = _previous_month(last_year, last_month)
    default_a, default_b = (prior_year, prior_month), (last_year, last_month)

    raw_a, raw_b = request.GET.get("a"), request.GET.get("b")
    picked_a = _parse_month(raw_a) if raw_a is not None else default_a
    picked_b = _parse_month(raw_b) if raw_b is not None else default_b
    invalid_month = picked_a is None or picked_b is None
    selected_a = picked_a or default_a
    selected_b = picked_b or default_b

    month_options = []
    pointer = (current_year, current_month)
    for _ in range(60):
        month_options.append(_month_key(*pointer))
        pointer = _previous_month(*pointer)
    for extra in (selected_a, selected_b):
        key = _month_key(*extra)
        if key not in month_options:
            month_options.append(key)

    role = role_of(request.user)
    branch = None
    branches = Branch.objects.all().order_by("name")
    requested_branch = request.GET.get("branch", "")
    afsariyeh_only = False
    if role == "manager":
        branch = getattr(request.user.profile, "branch", None)
        if branch is None:
            raise PermissionDenied("Branch manager must be assigned to a branch.")
        branches = branches.filter(pk=branch.pk)
    elif requested_branch.isdecimal():
        branch = branches.filter(pk=int(requested_branch)).first()
    elif requested_branch == "afsariyeh":
        afsariyeh_only = True

    source = request.GET.get("source", "")
    source_options = list(ReferralLead.SOURCE) + [("direct", "مراجعه مستقیم")]
    if source not in {code for code, _ in source_options}:
        source = ""
    service = request.GET.get("service", "")
    if service not in dict(FinancialTransaction.SALE_REASON):
        service = ""
    flower_raw = request.GET.get("flower", "")
    flower_id = int(flower_raw) if flower_raw.isdecimal() else None
    flowers = EmployeeProfile.objects.filter(
        role="call_center", is_active=True, user__is_active=True
    ).select_related("user").order_by("user__first_name", "user__last_name")

    # Match the Finance page's approved income. Keep non-IR countries out of a
    # single-IRR report; allow legacy branches with no country assignment.
    scope = FinancialTransaction.objects.filter(
        Q(branch__country__code="IR") | Q(branch__country__isnull=True) | Q(branch__isnull=True),
        entry_type="inc",
    )
    scope = _apply_transaction_filters(scope, branch, flower_id, source, service)
    if afsariyeh_only:
        scope = scope.filter(raw_data__payment_kind=DEPOSIT_KIND)
    approved = scope.filter(review_status="approved")
    pending = scope.filter(review_status="pending")

    first = _month_snapshot(approved, pending, *selected_a)
    second = _month_snapshot(approved, pending, *selected_b)
    # Keep the important payment terminals visible even when neither month has
    # a receipt. Pinned zeros are labels only, never artificial transactions.
    for channel in ("POS-S", "POS-H", "CC-S", "CC-G"):
        for snapshot in (first, second):
            snapshot["parts"]["payments"].setdefault(
                channel, {"total": ZERO, "count": 0}
            )
    comparisons = {
        kind: _comparison_rows(
            first["parts"][kind], second["parts"][kind], first["total"], second["total"]
        )
        for kind in ("payments", "branches", "services", "sources", "flowers")
    }
    max_day = max(first["number_of_days"], second["number_of_days"])
    chart_rows = []
    for day in range(1, max_day + 1):
        a = first["days"].get(day, {})
        b = second["days"].get(day, {})
        chart_rows.append({
            "day": day,
            "a": float(_millions(a.get("total", ZERO))) if day <= first["number_of_days"] else None,
            "b": float(_millions(b.get("total", ZERO))) if day <= second["number_of_days"] else None,
            "a_count": a.get("count", 0) if day <= first["number_of_days"] else None,
            "b_count": b.get("count", 0) if day <= second["number_of_days"] else None,
        })
    incomplete = (selected_a == (current_year, current_month) or selected_b == (current_year, current_month))
    total_delta = second["total"] - first["total"]
    return render(request, "core/finance_month_comparison.html", {
        "month_a": first, "month_b": second,
        "month_options": month_options,
        "invalid_month": invalid_month,
        "branches": branches, "branch": branch,
        "afsariyeh_only": afsariyeh_only,
        "flowers": flowers, "flower_id": flower_id,
        "source_options": source_options, "source": source,
        "service_options": FinancialTransaction.SALE_REASON, "service": service,
        "payments": comparisons["payments"],
        "branch_rows": comparisons["branches"],
        "services": comparisons["services"],
        "sources": comparisons["sources"],
        "flower_rows": comparisons["flowers"],
        "delta_m": _millions(total_delta),
        "delta_pct": _percentage_delta(first["total"], second["total"]),
        "incomplete": incomplete,
        "insights": _insights(first, second, comparisons, incomplete=incomplete),
        "chart_rows": chart_rows,
        "chart_data": {"rows": chart_rows, "a": first["key"], "b": second["key"]},
    })
