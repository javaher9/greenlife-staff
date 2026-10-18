from datetime import datetime, time, timedelta
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET
from functools import wraps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.conf import settings
from .models import ReferralLead, MarketingWorkerState, MarketingSmsPlan
from .bulk_sms_views import _may_manage_bulk_sms
from .marketing_sms_views import _is_allowed as _can_send_direct_sms


def marketing_manager_required(view):
    @wraps(view)
    @login_required
    def wrapped(request, *args, **kwargs):
        user = request.user
        profile = getattr(user, "profile", None)
        if not user.is_active or (profile and not profile.is_active):
            raise PermissionDenied("حساب کاربری فعال نیست.")
        executive = (user.username or "").lower() in settings.EXECUTIVE_USERNAMES
        role = getattr(profile, "role", None)
        if not (executive or user.is_superuser or role in ("admin", "internal_manager", "manager")):
            raise PermissionDenied("دسترسی مدیریتی به اتاق فرمان لید ندارید.")
        return view(request, *args, **kwargs)
    return wrapped

AGENTS = [
    ("commander","Lead Commander","فرمانده لید","جمع‌بندی و اولویت‌بندی فرصت‌ها"),
    ("luxury","Luxury Lead Scout","شکارچی لید VIP","کشف کانال‌های پریمیوم و باکیفیت"),
    ("source","Lead Source Scout","کشف منابع","پیدا کردن منابع جدید قابل تست"),
    ("seo","Google / SEO Agent","گوگل و سئو","فرصت‌های High-Intent و صفحات تجاری"),
    ("instagram","Instagram Agent","اینستاگرام","بهبود ورودی و Qualification"),
    ("partner","Partnership Agent","پارتنرشیپ","کشف و ارزیابی شرکای مناسب"),
    ("quality","Lead Quality Agent","کیفیت لید","پایش وضعیت نوبت و فروش در CRM"),
    ("sms","SMS Strategy Agent","برنامه‌ریز پیامک","ایده و متن روزانه برای گروه‌های مختلف مخاطبان"),
]

def _snapshot():
    """Read-only snapshot. Worker statuses are not invented or inferred from CRM activity."""
    now = timezone.now()
    day = timezone.localdate(now)
    start = timezone.make_aware(datetime.combine(day, time.min))
    end = start + timedelta(days=1)

    # Only records explicitly assigned to the Iran market; no historical leads.
    # ReferralLead has no reliable destination-branch field: this KPI is Iran-wide,
    # not a claimed Niyavaran/Punak or marketing-only acquisition count.
    todays_leads = ReferralLead.objects.filter(
        country__code="IR", created_at__gte=start, created_at__lt=end
    )
    total_today = todays_leads.aggregate(total=Count("id"))["total"] or 0
    recent = list(todays_leads.order_by("-created_at").values("id", "created_at")[:8])
    events = [
        {
            "id": item["id"],
            "time": timezone.localtime(item["created_at"]).strftime("%H:%M"),
            "agent": "ثبت در CRM",
            "message": "لید جدید در اپ ثبت شد",
        }
        for item in recent
    ]

    states = {
        item.key: item for item in MarketingWorkerState.objects.filter(
            key__in=[key for key, *_ in AGENTS]
        )
    }
    def is_running(key):
        item = states.get(key)
        return bool(item and item.heartbeat_at and
                    item.heartbeat_at >= now - timedelta(seconds=180))

    agents = [{
        "key": key, "name": name, "fa": fa, "mission": mission,
        "status": ("running" if is_running(key) else "waiting"),
        "status_label": ("RUNNING" if is_running(key) else "WAITING"),
        "activity": (states[key].activity if is_running(key) else "در انتظار اجرای واقعی Worker"),
        "heartbeat": (timezone.localtime(states[key].heartbeat_at).isoformat()
                      if is_running(key) else None),
    } for key, name, fa, mission in AGENTS]
    plan = MarketingSmsPlan.objects.filter(day=day).first()
    sms_plan = ({
        "day": plan.day.isoformat(),
        "segment": plan.segment_title,
        "segment_key": plan.segment_key,
        "body": plan.body,
        "reason": plan.rationale,
        "candidate_count": plan.candidate_count,
        "preview_limited": plan.preview_limited,
        "status": "proposal",
    } if plan else None)
    active_count = sum(1 for agent in agents if agent["status"] == "running")
    return {
        "server_time": now.isoformat(),
        "live": True,
        "crm_connected": True,
        "scope": "IR",
        "agents": agents,
        "kpi": {
            "agents": len(agents), "active": active_count,
            "new_today": total_today,
            # These are not measurable reliably from current fields.
            # null means unknown; never substitute zeros.
            "qualified_today": None,
            "opportunities": None,
            "revenue_today": None,
        },
        "events": events,
        "sms_plan": sms_plan,
        "note": ("پایش داخلی CRM و برنامه‌ریزی پیامک فعال است؛ اتصال مستقیم جست‌وجوی وب/اینستاگرام هنوز فعال نیست و پیامک خودکار ارسال نمی‌شود."
                 if active_count else
                 "شمارش CRM فعال است؛ Workerهای مارکتینگ هنوز سیگنال تازه ندارند."),
    }

@marketing_manager_required
def lead_command_center(request):
    # Reuse the existing SMS permission gates; never broaden sending access.
    return render(request, "core/lead_command_center.html", {
        "snapshot": _snapshot(),
        "can_bulk_sms": _may_manage_bulk_sms(request.user),
        "can_direct_sms": _can_send_direct_sms(request.user),
    })

@require_GET
@marketing_manager_required
def lead_command_center_live(request):
    return JsonResponse(_snapshot(),json_dumps_params={"ensure_ascii":False})
