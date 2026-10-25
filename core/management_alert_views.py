"""Role-aware, read-only management alert center.

No migrations or external services required. Calculations use actual Staff rows.
"""
from datetime import datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.utils.html import format_html

from .models import Task, ReferralLead, ReferralProfile, CustomerServiceRequest
from .views import role_of


def _item(code, title, detail, href, severity="warning", owner=""):
    return dict(code=code, title=title, detail=detail, href=href,
                severity=severity, owner=owner)


def collect_alerts(user):
    role = role_of(user)
    today = timezone.localdate()
    now = timezone.localtime()
    alerts = []
    # Tasks: staff see only their own; administrators see organizational backlog.
    tasks = Task.objects.filter(status__in=("todo", "doing"), due_date__lt=today)
    if role not in ("admin", "internal_manager"):
        tasks = tasks.filter(assigned_to=user)
    for task in tasks.select_related("assigned_to").order_by("due_date")[:30]:
        days = (today-task.due_date).days
        alerts.append(_item(
            f"task:{task.pk}", "وظیفه عقب‌افتاده: "+task.title,
            f"{days} روز تأخیر · موعد {task.due_date}",
            f"/tasks/{task.pk}/", "danger" if days >= 3 else "warning",
            task.assigned_to.get_full_name() or task.assigned_to.username,
        ))
    # Customer-club requests: same role/branch/kind scoping as the staff queue.
    # Only pending requests are counted; completed bookings never trigger alerts.
    if role in ("admin", "internal_manager", "manager", "call_center", "consultant"):
        pending = CustomerServiceRequest.objects.filter(status="pending")
        profile = getattr(user, "profile", None)
        if role == "call_center":
            pending = pending.filter(kind="visit")
        elif role == "consultant":
            pending = pending.filter(kind="device", branch_id=profile.branch_id) if profile and profile.branch_id else pending.none()
        elif role == "manager":
            pending = pending.filter(branch_id=profile.branch_id) if profile and profile.branch_id else pending.none()
        count = pending.count()
        if count:
            alerts.append(_item(
                "customer-requests-pending", "درخواست‌های مشتریان در انتظار رسیدگی",
                f"{count} درخواست جدید در صف · برای مشاهده و پیگیری کلیک کنید",
                "/staff/customer-requests/?status=pending",
                "warning", "مسئول مربوطه",
            ))
    # Sales network: organization-level target, never attributed to individuals.
    if role in ("admin", "internal_manager", "referral_supervisor"):
        start = timezone.make_aware(datetime.combine(today, time.min),
                                    timezone.get_current_timezone())
        end = start + timedelta(days=1)
        leads = ReferralLead.objects.filter(created_at__gte=start, created_at__lt=end).count()
        members = ReferralProfile.objects.filter(
            created_at__gte=start, created_at__lt=end, sponsor__isnull=False).count()
        # During the day show progress, but do not falsely label missed daily goals.
        for key, name, actual, target, href in (
            ("network-leads", "لید روزانه شبکه فروش", leads, 10, "/referrals/leads/"),
            ("network-members", "عضو جدید شبکه فروش", members, 5, "/referrals/network/"),
        ):
            if actual < target:
                alerts.append(_item(
                    key, name, f"{actual} از {target} · مانده {target-actual} · مهلت پایان روز",
                    href, "info", "ناظر شبکه فروش",
                ))
    return alerts


@login_required
def alert_center(request):
    items = collect_alerts(request.user)
    return render(request, "core/alert_center.html", {
        "alerts": items, "alert_count": len(items),
        "role": role_of(request.user),
    })


@login_required
def alert_center_api(request):
    items = collect_alerts(request.user)
    return JsonResponse({"count": len(items), "alerts": items})
