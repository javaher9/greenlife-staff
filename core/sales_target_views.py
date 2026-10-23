"""Executive-only sales target dashboard (approved/manual receipts, no fabricated targets)."""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Sum, Q
from django.db.models.functions import TruncDate, Coalesce
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from .call_center_identity import call_center_display_name
from .jalali import gregorian_to_jalali, jalali_to_gregorian
from .models import Branch, EmployeeProfile, FinancialTransaction
from .sales_target_models import SalesTargetBand, TargetPercentPolicy

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
    branches = list(Branch.objects.filter(is_active=True).filter(Q(country__code="IR") | Q(country__isnull=True)).exclude(name__icontains="ارومیه").exclude(name__icontains="افسریه").order_by("name"))
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

    policy = TargetPercentPolicy.objects.filter(period_year=jy, period_month=jm).first()
    if policy is None:
        policy = TargetPercentPolicy(period_year=jy, period_month=jm)
    if request.method == "POST":
        action = (request.POST.get("action") or "set_floor").strip()
        try:
            def amount(name):
                result = Decimal((request.POST.get(name) or "").replace(",", "").strip())
                if not result.is_finite():
                    raise InvalidOperation()
                return result

            if action == "save_all":
                # Validate ALL submitted changes before writing anything. A missing
                # or duplicate subject cannot silently replace someone else's floor.
                form_policy = TargetPercentPolicy(
                    period_year=jy, period_month=jm,
                    heavy_percent=amount("heavy_percent"),
                    target_one_percent=amount("target_one_percent"),
                    target_two_percent=amount("target_two_percent"),
                    updated_by=user,
                )
                form_policy.full_clean()
                edited = request.POST.getlist("subject")
                if len(edited) != len(set(edited)) or set(edited) != set(valid_subjects):
                    raise ValidationError("لیست افراد یا مراکز تغییر کرده است. صفحه را دوباره باز کنید.")
                records = []
                for subject in edited:
                    entered = (request.POST.get(f"floor_{subject}") or "").replace(",", "").strip()
                    if not entered:
                        continue  # no existing target is created from empty input
                    floor = Decimal(entered)
                    if not floor.is_finite() or floor <= 0:
                        raise ValidationError("کف فروش همه ردیف‌های پرشده باید مثبت باشد.")
                    bounds = form_policy.bands(floor)
                    scope, branch, employee = valid_subjects[subject]
                    values = dict(zip(("heavy_limit", "sales_floor", "target_one", "target_two"), bounds))
                    obj = SalesTargetBand(
                        key=f"{period}:{subject}", period_year=jy, period_month=jm,
                        scope=scope, branch=branch, employee=employee,
                        updated_by=user, **values,
                    )
                    obj.full_clean(exclude=["key"])  # update of an existing unique monthly subject is valid
                    records.append((obj.key, dict(
                        period_year=jy, period_month=jm, scope=scope, branch=branch,
                        employee=employee, updated_by=user, **values,
                    )))
                with transaction.atomic():
                    TargetPercentPolicy.objects.update_or_create(
                        period_year=jy, period_month=jm,
                        defaults={
                            "heavy_percent":form_policy.heavy_percent,
                            "target_one_percent":form_policy.target_one_percent,
                            "target_two_percent":form_policy.target_two_percent,
                            "updated_by":user,
                        },
                    )
                    for key, defaults in records:
                        SalesTargetBand.objects.update_or_create(key=key, defaults=defaults)
                messages.success(request, f"همه تغییرات ذخیره شدند؛ {len(records)} کف فروش و درصدهای عمومی به‌روزرسانی شد.")
            elif action == "set_policy":
                candidate = TargetPercentPolicy(
                    period_year=jy, period_month=jm,
                    heavy_percent=amount("heavy_percent"),
                    target_one_percent=amount("target_one_percent"),
                    target_two_percent=amount("target_two_percent"),
                    updated_by=user,
                )
                candidate.full_clean()
                TargetPercentPolicy.objects.update_or_create(
                    period_year=jy, period_month=jm,
                    defaults={
                        "heavy_percent":candidate.heavy_percent,
                        "target_one_percent":candidate.target_one_percent,
                        "target_two_percent":candidate.target_two_percent,
                        "updated_by":user,
                    },
                )
                messages.success(request, "درصدها ذخیره شدند؛ محدوده‌های رنگی تمام عقربه‌ها بر اساس درصدهای جدید محاسبه می‌شوند.")
            elif action == "set_floor":
                subject = (request.POST.get("subject") or "").strip()
                if subject not in valid_subjects:
                    raise ValidationError("فروشنده یا مرکز معتبر نیست.")
                floor = amount("sales_floor")
                if floor <= 0:
                    raise ValidationError("کف فروش باید بزرگ‌تر از صفر باشد.")
                values = dict(zip(
                    ("heavy_limit","sales_floor","target_one","target_two"),
                    policy.bands(floor),
                ))
                scope, branch, employee = valid_subjects[subject]
                band = SalesTargetBand(
                    key=f"{period}:{subject}", period_year=jy, period_month=jm,
                    scope=scope, branch=branch, employee=employee,
                    updated_by=user, **values,
                )
                band.full_clean()
                SalesTargetBand.objects.update_or_create(
                    key=band.key,
                    defaults={
                        "period_year":jy, "period_month":jm, "scope":scope,
                        "branch":branch, "employee":employee,
                        "updated_by":user, **values,
                    },
                )
                messages.success(request, "کف فروش ذخیره شد؛ سه مرز دیگر خودکار محاسبه شدند.")
            else:
                raise ValidationError("درخواست نامعتبر است.")
        except (InvalidOperation, ValidationError, ValueError, TypeError):
            messages.error(request, "عددهای معتبر و مثبت وارد کن. درصد سنگین کمتر از ۱۰۰، تارگت ۱ بیشتر از ۱۰۰ و تارگت ۲ بالاتر از تارگت ۱ باشد.")
        return HttpResponseRedirect(f"{reverse('sales_targets_dashboard')}?year={jy}&month={jm}&edit=1")

    configs = SalesTargetBand.objects.filter(period_year=jy, period_month=jm)
    # Calculate at read time as well: updating global percentages immediately
    # changes the actual boundaries, colors, and needle positions everywhere.
    plans = {}
    for stored in configs:
        heavy, floor, one, two = policy.bands(stored.sales_floor)
        plans[stored.key.removeprefix(period + ":")] = SimpleNamespace(
            heavy_limit=heavy, sales_floor=floor,
            target_one=one, target_two=two,
        )

    start = timezone.make_aware(datetime.combine(start_date, time.min))
    end = timezone.make_aware(datetime.combine(end_date, time.min))
    # Source is restricted to approved manual income; CRM imports can overlap
    # with these same receipts and must not silently be double counted.
    income = FinancialTransaction.objects.filter(
        source="manual", entry_type="inc", review_status="approved",
        occurred_at__gte=start, occurred_at__lt=end,
    )
    by_branch = {r["branch_id"]: _money(r["amount"]) for r in income.values("branch_id").annotate(amount=Sum("amount"))}
    # The consultant owns the finalized consultation; a receptionist can record
    # the money on their behalf. Use the plan consultant first, then recorder.
    by_consultant = {r["seller_id"]: _money(r["amount"]) for r in
        income.annotate(seller_id=Coalesce(
            "appointment__consultation_plan__consultant_id", "recorded_by_id",
        )).values("seller_id").annotate(amount=Sum("amount"))}
    # The first booking owner is the fallback for historical rows.
    by_flower = {r["flower_id"]: _money(r["amount"]) for r in
        income.annotate(flower_id=Coalesce(
            "call_center_owner_id", "appointment__lead__first_appointment_by_id",
        )).filter(flower_id__isnull=False).values("flower_id").annotate(amount=Sum("amount"))}
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
    has_sales = any(amount > ZERO for amount in daily_map.values())
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
        "has_sales":has_sales, "is_first_days":start_date <= today < start_date + timedelta(days=3),
        "shortfall":max(ZERO, (overall["plan"].target_one-total)) if overall["plan"] else None,
        "ranking":ranking, "warnings":warnings, "trend":trend,
        "deposit_count":deposit_count, "edit_rows":edit_rows,
        "edit_mode":request.GET.get("edit") == "1",
        "configured_count":len(plans), "person_count":len(all_people),
        "target_policy":policy,
    })


@login_required
def my_sales_targets(request):
    """Read-only personal sales goals; monthly statuses only, no daily penalties."""
    profile = getattr(request.user, "profile", None)
    if not profile or not profile.is_active or profile.role not in ("call_center", "consultant"):
        raise PermissionDenied("این صفحه مختص گل‌های کال‌سنتر و مشاوران فروش است.")
    # Staff must never choose another person's ID.
    jy, jm, start_date, end_date, today = _month_params(request)
    period = f"{jy}-{jm:02d}"
    key = f"{'flower' if profile.role == 'call_center' else 'consultant'}:{request.user.pk}"
    policy = TargetPercentPolicy.objects.filter(period_year=jy, period_month=jm).first()
    if policy is None:
        policy = TargetPercentPolicy(period_year=jy, period_month=jm)
    saved = SalesTargetBand.objects.filter(key=f"{period}:{key}").first()
    plan = None
    if saved:
        heavy, floor, one, two = policy.bands(saved.sales_floor)
        plan = SimpleNamespace(heavy_limit=heavy, sales_floor=floor, target_one=one, target_two=two)
    period_start = timezone.make_aware(datetime.combine(start_date, time.min))
    period_end = timezone.make_aware(datetime.combine(end_date, time.min))
    today_start = timezone.make_aware(datetime.combine(today, time.min))
    tomorrow_start = today_start + timedelta(days=1)
    receipts = FinancialTransaction.objects.filter(
        source="manual", entry_type="inc", review_status="approved",
        occurred_at__gte=period_start, occurred_at__lt=period_end,
    )
    if profile.role == "call_center":
        receipts = receipts.annotate(seller=Coalesce(
            "call_center_owner_id", "appointment__lead__first_appointment_by_id",
        ))
        display_name = call_center_display_name(request.user)
    else:
        receipts = receipts.annotate(seller=Coalesce(
            "appointment__consultation_plan__consultant_id", "recorded_by_id",
        ))
        display_name = request.user.get_full_name() or request.user.username
    mine = receipts.filter(seller=request.user.pk)
    monthly = _money(mine.aggregate(value=Sum("amount"))["value"])
    daily = _money(mine.filter(occurred_at__gte=today_start, occurred_at__lt=tomorrow_start).aggregate(value=Sum("amount"))["value"])
    days = (end_date - start_date).days
    daily_floor = (plan.sales_floor / Decimal(days)).quantize(Decimal("0.01")) if plan else None
    upper_percent = policy.target_two_percent * Decimal("1.20")
    segments = [
        policy.heavy_percent, Decimal("100") - policy.heavy_percent,
        policy.target_one_percent - Decimal("100"),
        policy.target_two_percent - policy.target_one_percent,
        upper_percent - policy.target_two_percent,
    ]
    # Daily target is deliberately indicative and never a penalty decision.
    row = _gauge_row(key, display_name, monthly, {key:plan} if plan else {})
    return render(request, "core/my_sales_targets.html", {
        "row":row, "period_label":f"{jy}/{jm:02d}", "monthly":monthly,
        "daily":daily, "daily_floor":daily_floor, "days":days,
        "is_flower":profile.role=="call_center", "plan":plan,
        "policy":policy, "segments":segments, "avatar":profile.avatar.url if profile.avatar else "",
        "source_note":"فقط دریافت‌های دستی تأییدشده منتسب به حساب شما در این گزارش نمایش داده شده‌اند.",
    })
