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


def collect_alerts(user, request=None):
    role = role_of(user)
    today = timezone.localdate()
    now = timezone.localtime()
    alerts = []
    if request is None:
        from types import SimpleNamespace
        from .country_workspace import country_for_user
        request=SimpleNamespace(user=user,country_scope=country_for_user(user),country_scope_code='')
    from .internal_manager_scope import supervised_users
    from .country_workspace import scoped_queryset

    # Tasks: staff see only their own; administrators see organizational backlog.
    tasks = Task.objects.filter(status__in=("todo", "doing"), due_date__lt=today)
    if role in ("admin", "internal_manager", "manager"):
        tasks=tasks.filter(assigned_to__in=supervised_users(request))
    else:
        tasks = tasks.filter(assigned_to=user)
    for task in tasks.select_related("assigned_to__profile").order_by("due_date")[:30]:
        days = (today-task.due_date).days
        alerts.append(_item(
            f"task:{task.pk}", "وظیفه عقب‌افتاده: "+task.title,
            f"{days} روز تأخیر · موعد {task.due_date}",
            (f"/employees/{task.assigned_to.profile.pk}/360/" if role in ("admin","internal_manager","manager") else f"/tasks/{task.pk}/"), "danger" if days >= 3 else "warning",
            task.assigned_to.get_full_name() or task.assigned_to.username,
        ))
    # Customer-club requests: same role/branch/kind scoping as the staff queue.
    # Only pending requests are counted; completed bookings never trigger alerts.
    if role in ("admin", "internal_manager", "manager", "call_center", "consultant"):
        from .customer_portal_views import _visible_staff_requests
        pending=_visible_staff_requests(request).filter(status__in=('pending','contacted'))
        count = pending.count()
        if count:
            alerts.append(_item(
                "customer-requests-pending", "درخواست‌های باز مشتریان",
                f"{count} درخواست جدید یا در حال پیگیری · برای مشاهده و پیگیری کلیک کنید",
                "/staff/customer-requests/?status=open",
                "warning", "مسئول مربوطه",
            ))
    if role in ('admin','internal_manager','referral_supervisor'):
        # Existing rows lack a reliable distinction between tests, imports and
        # genuinely acquired members/leads. Never present their count as success.
        href='/referrals/staff-monthly/' if role in ('admin','internal_manager') else '/referrals/network/'
        alerts.append(_item('acquisition-unknown','اعتبار شاخص جذب روزانه نیازمند تکمیل است',
            'داده کافی نیست؛ تفکیک جذب واقعی از تست و ورود قدیمی هنوز قابل اثبات نیست.',href,'info','مدیریت کال‌سنتر و شبکه فروش'))
    if role in ('admin','internal_manager'):
        from .operations_monitor import direct_gap
        from .models import OperationsIncident
        gap=direct_gap(country_id=getattr(getattr(request,'country_scope',None),'pk',None))
        if gap and gap['active']:
            alerts.append(_item('manual-dm-gap','وقفه در ثبت دستی دایرکت اینستاگرام',
                'بیش از دو ساعت در بازه فعال تهران، ثبت دستی معتبر ردیابی نشده؛ جریان ثبت بررسی شود.',
                ('/management/monitoring-history/' if role=='internal_manager' else '/instagram/manual/'),'warning','تیم ثبت دستی دایرکت'))
        past=scoped_queryset(request,OperationsIncident.objects.filter(resolved_at__isnull=True,day__lt=today)).exists()
        if past:
            alerts.append(_item('manual-dm-history','وقفه حل‌نشده ثبت دستی از روز قبل',
                'با تغییر روز رفع نشده است؛ علت توقف با تیم ثبت بررسی شود.', ('/management/monitoring-history/' if role=='internal_manager' else '/instagram/manual/'),'warning','تیم ثبت دستی دایرکت'))
    alerts.sort(key=lambda a: {'danger':0,'warning':1,'info':2}.get(a['severity'],3))
    return alerts


@login_required
def alert_center(request):
    items = collect_alerts(request.user,request=request)
    return render(request, "core/alert_center.html", {
        "alerts": items, "alert_count": len(items),
        "role": role_of(request.user),
    })


@login_required
def alert_center_api(request):
    items = collect_alerts(request.user,request=request)
    return JsonResponse({"count": len(items), "alerts": items})
