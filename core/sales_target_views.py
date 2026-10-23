"""Executive-only sales target dashboard (approved/manual receipts, no fabricated targets)."""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Sum, Q
from django.db.models.functions import TruncDate
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .call_center_identity import call_center_display_name
from .jalali import gregorian_to_jalali, jalali_to_gregorian
from .models import Branch, EmployeeProfile, FinancialTransaction
from .sales_target_models import SalesTargetBand

MILLION_TOMAN_RIAL = Decimal("10000000")
ZERO = Decimal("0")


def _money(amount):
    return ((amount or ZERO) / MILLION_TOMAN_RIAL).quantize(Decimal("0.01"))


def _month_params(request):
    today = timezone.localdate()
    jy, jm, _ = gregorian_to_jalali(today.year, today.month, today.day)
    try:
        year = int(request.POST.get("year") or request.GET.get("year") or jy)
        month = int(request.POST.get("month") or request.GET.get("month") or jm)
        if not (1300 <= year <= 1500 and 1 <= month <= 12):
            raise ValueError()
        start_date = datetime(*jalali_to_gregorian(year, month, 1)).date()
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        end_date = datetime(*jalali_to_gregorian(next_year, next_month, 1)).date()
        return year, month, start_date, end_date, today
    except (ValueError, TypeError):
        raise ValidationError("دوره شمسی نامعتبر است.")


def _gauge_row(key, label, value, plans, *, avatar="", people=None, group="", note=""):
    plan = plans.get(key)
    target_two = plan.target_two if plan else None
    percent = int(min(999, max(0, (value / target_two) * 100))) if target_two else None
    if plan is None:
        level = "unset"
        status = "تارگت تنظیم نشده"
    elif value < plan.heavy_limit:
        level, status = "heavy", "جریمه سنگین"
    elif value < plan.sales_floor:
        level, status = "light", "جریمه سبک"
    elif value < plan.target_one:
        level, status = "neutral", "نرمال"
    elif value < plan.target_two:
        level, status = "one", "تارگت ۱"
    else:
        level, status = "two", "تارگت ۲"
    return {
        "key": key, "label": label, "value": value, "plan": plan,
        "percentage": percent, "level": level, "status": status,
        "avatar": avatar, "people": people or [], "group": group, "note": note,
    }


@login_required
def sales_targets_dashboard(request):
    user = request.user
    profile = getattr(user, "profile", None)
    allowed = user.is_superuser or (
        profile and profile.role in ("admin", "internal_manager")
    )
    if not allowed:
        # Configured executive accounts are also authorized (not inferred from names).
        from .views import _is_executive_user
        allowed = _is_executive_user(user)
    if not allowed:
        raise PermissionDenied("این صفحه فقط برای مدیریت است.")

    try:
        jy, jm, start_date, end_date, today = _month_params(request)
    except ValidationError:
        messages.error(request, "دوره شمسی نامعتبر است.")
        return HttpResponseRedirect(reverse("sales_targets_dashboard"))

    prev_year, prev_month = (jy-1, 12) if jm == 1 else (jy, jm-1)
    next_year, next_month = (jy+1, 1) if jm == 12 else (jy, jm+1)
    period = f"{jy}-{jm:02d}"

    # Inactive branches (including closed Urmia) are intentionally omitted.
    branches = list(Branch.objects.filter(is_active=True).exclude(name__icontains="ارومیه").order_by("name"))
    profiles = list(EmployeeProfile.objects.filter(
        is_active=True, user__is_active=True, role__in=("call_center", "consultant"),
    ).select_related("user", "branch").order_by("user__first_name", "user__last_name", "user__username"))
    flowers = [p for p in profiles if p.role == "call_center"]
    consultants = [p for p in profiles if p.role == "consultant" and p.branch_id in {b.pk for b in branches}]

    valid_subjects = {
        "overall": ("overall", None, None),
        "call_center": ("call_center", None, None),
    }
    for b in branches:
        valid_subjects[f"branch:{b.pk}"] = ("branch", b, None)
    for p in flowers:
        valid_subjects[f"flower:{p.user_id}"] = ("flower", None, p.user)
    for p in consultants:
        valid_subjects[f"consultant:{p.user_id}"] = ("consultant", p.branch, p.user)

    if request.method == "POST":
        subject = (request.POST.get("subject") or "").strip()
        if subject not in valid_subjects:
            messages.error(request, "مورد انتخاب‌شده معتبر یا فعال نیست.")
        else:
            try:
                def amount(name):
                    value = (request.POST.get(name) or "").replace(",", "").strip()
                    return Decimal(value)
                values = {
                    "heavy_limit": amount("heavy_limit"),
                    "sales_floor": amount("sales_floor"),
                    "target_one": amount("target_one"),
                    "target_two": amount("target_two"),
                }
                scope, branch, employee = valid_subjects[subject]
                band = SalesTargetBand(
                    key=f"{period}:{subject}", period_year=jy, period_month=jm,
                    scope=scope, branch=branch, employee=employee,
                    updated_by=user, **values,
                )
                band.full_clean(exclude=["key"])
                SalesTargetBand.objects.update_or_create(
                    key=band.key, defaults={
                        "period_year":jy, "period_month":jm, "scope":scope,
                        "branch":branch, "employee":employee, "updated_by":user,
                        **values,
                    },
                )
                messages.success(request, "مرزهای فروش ذخیره شد؛ اعداد پاداش و جریمه صرفاً نمایشی هستند.")
            except (InvalidOperation, ValidationError, ValueError, TypeError):
                messages.error(request, "۴ عدد مثبت و صعودی وارد کنید: جریمه سنگین < کف فروش < تارگت ۱ < تارگت ۲.")
        return HttpResponseRedirect(f"{reverse('sales_targets_dashboard')}?year={jy}&month={jm}&edit=1")

    configs = SalesTargetBand.objects.filter(period_year=jy, period_month=jm)
    plans = {x.key.removeprefix(period + ":"): x for x in configs}

    start = timezone.make_aware(datetime.combine(start_date, time.min))
    end = timezone.make_aware(datetime.combine(end_date, time.min))
    # Source is restricted to approved manual income; CRM imports can overlap
    # with these same receipts and must not silently be double counted.
    income = FinancialTransaction.objects.filter(
        source="manual", entry_type="inc", review_status="approved",
        occurred_at__gte=start, occurred_at__lt=end,
    )
    by_branch = {r["branch_id"]: _money(r["amount"]) for r in income.values("branch_id").annotate(amount=Sum("amount"))}
    by_consultant = {r["recorded_by_id"]: _money(r["amount"]) for r in income.values("recorded_by_id").annotate(amount=Sum("amount"))}
    by_flower = {r["call_center_owner_id"]: _money(r["amount"]) for r in income.filter(
        call_center_owner__isnull=False
    ).values("call_center_owner_id").annotate(amount=Sum("amount"))}
    total = _money(income.filter(branch__in=branches).aggregate(value=Sum("amount"))["value"])

    # This is intentionally conservative: only explicitly identified deposit
    # transactions qualify. Other Afseriyeh receipts must not be presented as
    # deposits, even if they were brought in by call-center operators.
    deposits = income.filter(sale_origin="afsariyeh").filter(
        Q(description__icontains="بیعانه") | Q(service__icontains="بیعانه")
    )
    call_center_deposit = _money(deposits.aggregate(value=Sum("amount"))["value"])
    deposit_count = deposits.count()

    consultants_by_branch = defaultdict(list)
    consultant_cards = []
    for p in consultants:
        card = _gauge_row(
            f"consultant:{p.user_id}", p.user.get_full_name() or p.user.username,
            by_consultant.get(p.user_id, ZERO), plans,
            avatar=p.avatar.url if p.avatar else "", group=p.branch.name,
        )
        consultants_by_branch[p.branch_id].append(card)
        consultant_cards.append(card)

    branch_cards = []
    for b in branches:
        row = _gauge_row(
            f"branch:{b.pk}", b.name, by_branch.get(b.pk, ZERO),
            plans, people=consultants_by_branch[b.pk], group="مرکز",
        )
        branch_cards.append(row)

    flower_cards = [
        _gauge_row(
            f"flower:{p.user_id}", call_center_display_name(p.user),
            by_flower.get(p.user_id, ZERO), plans,
            avatar=p.avatar.url if p.avatar else "", group="کال‌سنتر",
        ) for p in flowers
    ]
    call_center_card = _gauge_row(
        "call_center", "کال‌سنتر", call_center_deposit, plans, group="بیعانه‌های شناسایی‌شده",
        note="فقط رسیدهای تأییدشده که صراحتاً «بیعانه» ثبت شده‌اند",
    )
    overall = _gauge_row("overall", "مجموع مراکز", total, plans)
    financial_cards = branch_cards + [call_center_card]
    all_people = consultant_cards + flower_cards
    warnings = [r for r in all_people if r["level"] in ("heavy", "light")]
    ranking = sorted(
        [r for r in all_people if r["percentage"] is not None],
        key=lambda r: r["percentage"], reverse=True,
    )[:5]

    daily = list(income.filter(branch__in=branches).annotate(
        day=TruncDate("occurred_at"),
    ).values("day").annotate(value=Sum("amount")).order_by("day"))
    daily_map = {r["day"]: _money(r["value"]) for r in daily}
    running = ZERO
    trend = []
    max_trend = max(total, overall["plan"].target_two if overall["plan"] else ZERO, Decimal("1"))
    d = start_date
    while d < end_date:
        running += daily_map.get(d, ZERO)
        _, _, jd = gregorian_to_jalali(d.year, d.month, d.day)
        trend.append({"day": jd, "amount": running, "height": float(running/max_trend*100)})
        d += timedelta(days=1)
    now_in_period = start_date <= today < end_date
    elapsed = (min(today+timedelta(days=1), end_date)-start_date).days if now_in_period else (end_date-start_date).days
    projection = (total * Decimal(len(trend)) / Decimal(elapsed)).quantize(Decimal("0.01")) if now_in_period and elapsed > 0 else None

    edit_rows = [
        {"key":key, "label":label, "band":plans.get(key), "scope":scope}
        for key, label, scope in (
            [("overall", "مجموع مراکز", "کل"), ("call_center", "کال‌سنتر ـ بیعانه", "کال‌سنتر")]
            + [(f"branch:{b.pk}", b.name, "مرکز") for b in branches]
            + [(f"consultant:{p.user_id}", p.user.get_full_name() or p.user.username, "مشاور") for p in consultants]
            + [(f"flower:{p.user_id}", call_center_display_name(p.user), "گل") for p in flowers]
        )
    ]
    return render(request, "core/sales_targets_dashboard.html", {
        "period_year":jy, "period_month":jm, "period_label":f"{jy}/{jm:02d}",
        "prev_year":prev_year, "prev_month":prev_month,
        "next_year":next_year, "next_month":next_month,
        "overall":overall, "branches":financial_cards,
        "flower_cards":flower_cards, "consultant_cards":consultant_cards,
        "total":total, "projection":projection,
        "shortfall":max(ZERO, (overall["plan"].target_one-total)) if overall["plan"] else None,
        "ranking":ranking, "warnings":warnings, "trend":trend,
        "deposit_count":deposit_count, "edit_rows":edit_rows,
        "edit_mode":request.GET.get("edit") == "1",
        "configured_count":len(plans), "person_count":len(all_people),
    })
