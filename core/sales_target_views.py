"""Executive-only sales target dashboard (approved/manual receipts, no fabricated targets)."""
from collections import defaultdict
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from types import SimpleNamespace

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, F, OuterRef, Q, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Greatest, TruncDate
from django.http import HttpResponseRedirect
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .call_center_deposit_views import DEPOSIT_MARKER
from .call_center_identity import call_center_display_name
from .jalali import gregorian_to_jalali, jalali_to_gregorian
from .models import Branch, ConsultationPlan, EmployeeProfile, FinancialTransaction
from .sales_target_models import SalesTargetBand, TargetPercentPolicy

MILLION_TOMAN_RIAL = Decimal("10000000")
ZERO = Decimal("0")


def _millions(amount):
    return (amount or ZERO) / MILLION_TOMAN_RIAL


def _money(amount):
    return _millions(amount).quantize(Decimal("0.01"))


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


def _gauge_row(key, label, value, plans, *, avatar="", people=None, group="", note="", paused=False):
    plan = plans.get(key)
    target_one = plan.target_one if plan and not paused else None
    # Exactly 100% means Target 1; Target 2 is a higher achievement level.
    percent = int(min(999, max(0, (value / target_one) * 100))) if target_one else None
    if paused:
        level, status = "paused", "غیرفعال"
    elif plan is None:
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
    bands = {
        key: format(limit * 100 / target_one, ".8f")
        for key, limit in zip(("heavy", "floor", "one", "two"),
                              (plan.heavy_limit, plan.sales_floor, plan.target_one, plan.target_two))
    } if target_one else {}
    return {
        "bands": bands,
        "color": {"heavy": "red", "light": "yellow", "neutral": "green", "one": "blue", "two": "purple"}.get(level, ""),
        "key": key, "label": label, "value": value, "plan": plan,
        "percentage": percent, "level": level, "status": status,
        "display_status": {"neutral": "کف فروش", "one": "تارگت اول", "two": "تارگت دوم"}.get(level, status),
        "avatar": avatar, "people": people or [], "group": group, "note": note,
    }


def _period_receipts(start_date, end_date):
    return FinancialTransaction.objects.filter(
        source="manual", entry_type="inc",
        occurred_at__gte=timezone.make_aware(datetime.combine(start_date, time.min)),
        occurred_at__lt=timezone.make_aware(datetime.combine(end_date, time.min)),
    )


def _deposit_filter():
    # The typed marker is authoritative. Keep older explicitly labeled
    # Afseriyeh deposits in both management and staff targets.
    return (Q(raw_data__has_key="payment_kind") & Q(raw_data__payment_kind=DEPOSIT_MARKER)) | (
        Q(sale_origin="afsariyeh") &
        (Q(description__icontains="بیعانه") | Q(service__icontains="بیعانه"))
    )


def _attributed_flower_receipts(receipts):
    return receipts.annotate(flower_id=Coalesce(
        "call_center_owner_id", "appointment__lead__first_appointment_by_id",
    )).filter(flower_id__isnull=False)


def _flower_branch_sales(start_date, end_date, *, user_id=None):
    """Branch sales in rial, excluding deposits already credited to the receipt owner."""
    start = timezone.make_aware(datetime.combine(start_date, time.min))
    end = timezone.make_aware(datetime.combine(end_date, time.min))
    plans = ConsultationPlan.objects.filter(
        status="paid", final_amount_toman__gt=0,
        appointment__lead__first_appointment_by__isnull=False,
    ).filter(
        Q(paid_at__gte=start, paid_at__lt=end) |
        Q(paid_at__isnull=True, appointment__appointment_date__gte=start_date,
          appointment__appointment_date__lt=end_date)
    ).exclude(appointment__status__in=("cancelled", "no_show")).annotate(
        flower_id=F("appointment__lead__first_appointment_by_id"),
        branch_id=F("appointment__branch_id"),
    )
    legacy = _attributed_flower_receipts(
        _period_receipts(start_date, end_date).filter(
            review_status="approved", appointment__consultation_plan__isnull=True,
        ).exclude(_deposit_filter()).exclude(sale_reason="skin_care"),
    )
    if user_id is not None:
        plans = plans.filter(flower_id=user_id)
        legacy = legacy.filter(flower_id=user_id)
    # A deposit belongs to the month and operator on its receipt. Deduct it
    # from the corresponding settled invoice even if the sale or deposit was
    # credited to a different month or operator.
    booked_deposits = FinancialTransaction.objects.filter(
        source="manual", entry_type="inc", review_status="approved",
        appointment_id=OuterRef("appointment_id"),
        occurred_at__lte=Coalesce(OuterRef("paid_at"), Value(end)),
    ).filter(_deposit_filter()).order_by().values("appointment_id").annotate(
        total=Sum("amount"),
    ).values("total")
    plans = plans.annotate(branch_amount=Greatest(
        F("final_amount_toman") * Decimal("10") - Coalesce(Subquery(booked_deposits), Value(ZERO)),
        Value(ZERO),
    ))
    totals = defaultdict(lambda: ZERO)
    for row in plans.order_by().values("flower_id", "branch_id").annotate(value=Sum("branch_amount")):
        totals[row["flower_id"], row["branch_id"]] += row["value"]
    for row in legacy.order_by().values("flower_id", "branch_id").annotate(value=Sum("amount")):
        totals[row["flower_id"], row["branch_id"]] += row["value"]
    return totals


def _band_from_policy(policy, floor):
    heavy, floor, one, two = policy.bands(floor)
    return SimpleNamespace(heavy_limit=heavy, sales_floor=floor, target_one=one, target_two=two)


def _team_flower_ids(year, month, *, closed):
    profiles = EmployeeProfile.objects.filter(role="call_center")
    if not closed:
        return set(profiles.filter(is_active=True, user__is_active=True).values_list("user_id", flat=True))
    # A later departure or role change must not erase a flower's monthly target.
    assigned = SalesTargetBand.objects.filter(
        period_year=year, period_month=month, scope__in=("flower_deposit", "flower"),
        employee_id__isnull=False,
    ).values_list("employee_id", flat=True)
    return set(profiles.values_list("user_id", flat=True)).union(assigned)


def _monthly_target_plans(policy, flower_ids, *, for_user_id=None):
    period = f"{policy.period_year}-{policy.period_month:02d}:"
    configs = SalesTargetBand.objects.filter(
        period_year=policy.period_year, period_month=policy.period_month,
    ).exclude(scope="call_center")
    if for_user_id is not None:
        configs = configs.filter(
            Q(scope="flower_deposit", employee_id__in=flower_ids) | Q(key=f"{period}flower:{for_user_id}")
        )
    plans, deposits = {}, []
    for key, scope, employee_id, floor in configs.values_list("key", "scope", "employee_id", "sales_floor"):
        band = _band_from_policy(policy, floor)
        plans[key.removeprefix(period)] = band
        if scope == "flower_deposit" and employee_id in flower_ids:
            deposits.append(band)
    if deposits:
        # Sum the individually rounded thresholds so the team target is exactly
        # the sum of each flower's Target 1, including with fractional floors.
        plans["call_center"] = SimpleNamespace(**{
            field: sum(getattr(band, field) for band in deposits)
            for field in ("heavy_limit", "sales_floor", "target_one", "target_two")
        })
    return plans


def _percent_text(value, *, rounding=None):
    rounded = value.quantize(Decimal("0.01"), rounding=rounding)
    return format(rounded, "f").rstrip("0").rstrip(".")


def _call_center_color_guides(gauges):
    # Individual monetary bands are rounded before aggregation. Share a legend
    # only when its displayed boundaries are the same for all relevant gauges.
    grouped = {}
    for label, gauge in gauges:
        bands = gauge["bands"]
        if bands:
            boundaries = tuple(_percent_text(Decimal(bands[key])) for key in ("heavy", "floor", "two"))
            grouped.setdefault(boundaries, []).append(label)
    return [
        {"heavy": heavy, "floor": floor, "two": two, "label": " و ".join(labels) if len(grouped) > 1 else ""}
        for (heavy, floor, two), labels in grouped.items()
    ] or [{}]


def _call_center_gauge(key, label, amount, plans, *, paused=False):
    gauge = _gauge_row(key, label, _millions(amount), plans, paused=paused)
    plan = gauge["plan"]
    if paused or plan is None:
        return gauge

    progress = max(ZERO, gauge["value"]) * 100 / plan.target_one
    # Do not round a near miss to 100% or turn a small first deposit into zero.
    gauge["progress_text"] = "<0.01%" if 0 < progress < Decimal("0.01") else _percent_text(
        progress, rounding=ROUND_DOWN,
    ) + "%"

    # SVG pathLength is 100. Keep the dial fixed to the configured bands,
    # including when an operator exceeds the end of the scale.
    maximum = plan.target_two * Decimal("1.20")
    stops = [ZERO, plan.heavy_limit, plan.sales_floor, plan.target_one, plan.target_two, maximum]
    positions = [float(stop / maximum * 100) for stop in stops]
    segments = []
    for color, start, end in zip(("red", "yellow", "green", "blue", "purple"), positions, positions[1:]):
        gap = min(0.42, (end - start) / 4)
        left = start + gap if start else start
        right = end - gap if end < 100 else end
        segments.append((color, f"0 {left:.4f} {right - left:.4f} 100"))
    gauge["segments"] = segments
    fraction = min(Decimal("1"), max(ZERO, gauge["value"] / maximum))
    gauge["needle_angle"] = format(155 + 230 * fraction, ".4f")
    return gauge


def _call_center_targets(user, jy, jm, start_date, end_date, today):
    """Build the shared and personal cards from the same month and management settings."""
    personal_key = f"flower:{user.pk}"
    deposit_key = f"flower_deposit:{user.pk}"
    policy = TargetPercentPolicy.objects.filter(period_year=jy, period_month=jm).first()
    if policy is None:
        policy = TargetPercentPolicy(period_year=jy, period_month=jm)
    flower_ids = _team_flower_ids(jy, jm, closed=end_date <= today)
    plans = _monthly_target_plans(policy, flower_ids, for_user_id=user.pk)
    daily_plans = {}
    if "call_center" in plans:
        plan = plans["call_center"]
        days = Decimal((end_date - start_date).days)
        daily_plans["call_center"] = SimpleNamespace(**{
            name: value / days for name, value in vars(plan).items()
        })

    deposits = _attributed_flower_receipts(_period_receipts(start_date, end_date).filter(_deposit_filter()))
    team = deposits.filter(review_status="approved", flower_id__in=flower_ids)
    day_start = timezone.make_aware(datetime.combine(today, time.min))
    day_end = timezone.make_aware(datetime.combine(today + timedelta(days=1), time.min))
    day_filter = Q(occurred_at__gte=day_start, occurred_at__lt=day_end)
    team_totals = team.aggregate(month=Sum("amount"), day=Sum("amount", filter=day_filter))
    own_deposits = deposits.filter(flower_id=user.pk)
    own_totals = own_deposits.aggregate(
        approved=Sum("amount", filter=Q(review_status="approved")),
        pending=Count("pk", filter=Q(review_status="pending")),
    )
    own_deposit = own_totals["approved"] or ZERO
    sales = _flower_branch_sales(start_date, end_date, user_id=user.pk)
    own_sales = own_deposit + sum(sales.values(), ZERO)
    team_month = _call_center_gauge("call_center", "ماهانه", team_totals["month"], plans)
    personal_deposit = _call_center_gauge(deposit_key, "بیعانه‌های من", own_deposit, plans)
    personal = _call_center_gauge(
        personal_key, "مجموع فروش من", own_sales, plans,
        paused=not settings.CALL_CENTER_COMBINED_SALES_TARGET_ENABLED,
    )
    return {
        "period_label": f"{jy}/{jm:02d}",
        "team_month": team_month,
        "team_day": _call_center_gauge("call_center", "روزانه", team_totals["day"], daily_plans),
        "personal_deposit": personal_deposit, "personal": personal,
        "color_guides": _call_center_color_guides((
            ("بیعانهٔ تیم", team_month), (personal_deposit["label"], personal_deposit), (personal["label"], personal),
        )),
        "current_month": start_date <= today < end_date,
        "has_approved_deposits": own_deposit > ZERO,
        "has_pending_deposits": bool(own_totals["pending"]),
        "own_deposits": own_deposits, "own_branch_sales": sales,
    }


def call_center_dashboard_targets(user):
    today = timezone.localdate()
    jy, jm, _ = gregorian_to_jalali(today.year, today.month, today.day)
    ny, nm = (jy+1, 1) if jm == 12 else (jy, jm+1)
    start = datetime(*jalali_to_gregorian(jy, jm, 1)).date()
    end = datetime(*jalali_to_gregorian(ny, nm, 1)).date()
    return _call_center_targets(user, jy, jm, start, end, today)


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

    valid_subjects = {"overall": ("overall", None, None)}
    for b in branches:
        valid_subjects[f"branch:{b.pk}"] = ("branch", b, None)
    for p in flowers:
        valid_subjects[f"flower:{p.user_id}"] = ("flower", None, p.user)
        valid_subjects[f"flower_deposit:{p.user_id}"] = ("flower_deposit", None, p.user)

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
                # Validate updates against the existing row, not as a new
                # conflicting monthly policy (unique year/month constraint).
                form_policy.full_clean(exclude=["id", "period_year", "period_month"])
                # A manager may still be editing an open pre-rollout form. Save
                # the flower entries and discard its obsolete manual team row.
                edited = [s for s in request.POST.getlist("subject") if s != "call_center"]
                if len(edited) != len(set(edited)) or not edited or any(s not in valid_subjects for s in edited):
                    raise ValidationError("فهرست تنظیمات نامعتبر است؛ صفحه را تازه‌سازی کنید.")
                # Staff may be added/removed while the manager edits. Do not
                # reject all floors simply because the live roster changed.
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
                    try:
                        obj.full_clean(exclude=["key"])
                    except ValidationError as err:
                        raise ValidationError(f"خطا در کف فروش {subject}: {err}")
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
                messages.success(request, f"تغییرات با موفقیت ذخیره شد؛ {len(records)} کف فروش و درصدهای عمومی به‌روزرسانی شدند.")
            elif action == "set_policy":
                candidate = TargetPercentPolicy(
                    period_year=jy, period_month=jm,
                    heavy_percent=amount("heavy_percent"),
                    target_one_percent=amount("target_one_percent"),
                    target_two_percent=amount("target_two_percent"),
                    updated_by=user,
                )
                candidate.full_clean(exclude=["id", "period_year", "period_month"])
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
                if subject == "call_center":
                    raise ValidationError("تارگت بیعانهٔ تیم از جمع تارگت اول بیعانهٔ گل‌ها محاسبه می‌شود.")
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
                band.full_clean(exclude=["key"])  # existing keys are updated below
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
        except ValidationError as exc:
            messages.error(request, "تارگت ذخیره نشد: " + "؛ ".join(exc.messages))
        except (InvalidOperation, ValueError, TypeError):
            messages.error(request, "تارگت ذخیره نشد: عدد واردشده نامعتبر است. مقدارهای مثبت و درصدهای مرتب وارد کنید.")
        return HttpResponseRedirect(f"{reverse('sales_targets_dashboard')}?year={jy}&month={jm}&edit=1")

    flower_ids = _team_flower_ids(jy, jm, closed=end_date <= today)
    plans = _monthly_target_plans(policy, flower_ids)

    # CRM imports may overlap with these same receipts.
    income = _period_receipts(start_date, end_date).filter(review_status="approved")
    by_branch = {r["branch_id"]: _millions(r["amount"]) for r in income.values("branch_id").annotate(amount=Sum("amount"))}
    # The consultant owns the finalized consultation; a receptionist can record
    # the money on their behalf. Use the plan consultant first, then recorder.
    by_consultant = {r["seller_id"]: _millions(r["amount"]) for r in
        income.annotate(seller_id=Coalesce(
            "appointment__consultation_plan__consultant_id", "recorded_by_id",
        )).values("seller_id").annotate(amount=Sum("amount"))}
    deposits = _attributed_flower_receipts(income.filter(_deposit_filter())).filter(flower_id__in=flower_ids)
    by_flower = {}
    deposit_count = 0
    for row in deposits.order_by().values("flower_id").annotate(amount=Sum("amount"), receipts=Count("pk")):
        by_flower[row["flower_id"]] = row["amount"]
        deposit_count += row["receipts"]
    call_center_deposit = _millions(sum(by_flower.values(), ZERO))
    for (flower_id, _branch_id), amount in _flower_branch_sales(start_date, end_date).items():
        by_flower[flower_id] = by_flower.get(flower_id, ZERO) + amount
    total = _millions(income.filter(branch__in=branches).aggregate(value=Sum("amount"))["value"])

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
            _millions(by_flower.get(p.user_id, ZERO)), plans,
            avatar=p.avatar.url if p.avatar else "", group="کال‌سنتر",
            paused=not settings.CALL_CENTER_COMBINED_SALES_TARGET_ENABLED,
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
        {"key": key, "label": label, "band": plans.get(key), "scope": scope,
         "paused": key.startswith("flower:") and not settings.CALL_CENTER_COMBINED_SALES_TARGET_ENABLED}
        for key, label, scope in (
            [("overall", "مجموع مراکز", "کل")]
            + [(f"branch:{b.pk}", b.name, "مرکز") for b in branches]
            + [
                row for p in flowers for row in (
                    (f"flower:{p.user_id}", call_center_display_name(p.user), "مجموع فروش"),
                    (f"flower_deposit:{p.user_id}", call_center_display_name(p.user), "بیعانه"),
                )
            ]
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
        "configured_count":sum(row["band"] is not None for row in edit_rows), "person_count":len(all_people),
        "target_policy":policy,
    })


@login_required
def my_sales_targets(request):
    """Read-only personal sales goals; monthly statuses only, no daily penalties."""
    profile = getattr(request.user, "profile", None)
    if not request.user.is_active or not profile or not profile.is_active or profile.role not in ("call_center", "consultant"):
        raise PermissionDenied("این صفحه مختص گل‌های کال‌سنتر و مشاوران فروش است.")
    # Staff must never choose another person's ID.
    try:
        jy, jm, start_date, end_date, today = _month_params(request)
    except ValidationError:
        messages.error(request, "دوره شمسی نامعتبر است.")
        return redirect("my_sales_targets")
    if profile.role == "call_center":
        cx = _call_center_targets(request.user, jy, jm, start_date, end_date, today)
        branch_ids = {
            branch_id for (_, branch_id), amount in cx["own_branch_sales"].items()
            if amount > ZERO
        }
        branch_names = list(Branch.objects.filter(pk__in=branch_ids).order_by("name").values_list("name", flat=True))
        if None in branch_ids:
            branch_names.append("بدون شعبه")
        deposits = cx["own_deposits"].select_related("branch").order_by("-occurred_at")[:60]
        return render(request, "core/call_center/targets.html", {
            "targets": cx, "period_year": jy, "period_month": jm,
            "deposits": deposits, "branch_names": branch_names,
            "flower_name": call_center_display_name(request.user),
        })
    period = f"{jy}-{jm:02d}"
    key = f"consultant:{request.user.pk}"
    policy = TargetPercentPolicy.objects.filter(period_year=jy, period_month=jm).first()
    if policy is None:
        policy = TargetPercentPolicy(period_year=jy, period_month=jm)
    # Consultants are represented by their branch target, not a second
    # independently configurable target. Keep old rows intact for audit.
    if profile.role == "consultant" and profile.branch_id:
        key = f"branch:{profile.branch_id}"
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
    receipts = receipts.annotate(seller=Coalesce(
        "appointment__consultation_plan__consultant_id", "recorded_by_id",
    ))
    display_name = request.user.get_full_name() or request.user.username
    mine = receipts.filter(seller=request.user.pk)
    monthly = _millions(mine.aggregate(value=Sum("amount"))["value"])
    daily = _money(mine.filter(occurred_at__gte=today_start, occurred_at__lt=tomorrow_start).aggregate(value=Sum("amount"))["value"])
    days = (end_date - start_date).days
    daily_target = plan.target_one / Decimal(days) if plan else None
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
        "daily":daily, "daily_target":daily_target, "days":days,
        "is_flower":False, "plan":plan,
        "policy":policy, "segments":segments, "avatar":profile.avatar.url if profile.avatar else "",
        "source_note":"فقط دریافت‌های دستی تأییدشده منتسب به حساب شما در این گزارش نمایش داده شده‌اند.",
    })
