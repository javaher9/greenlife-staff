"""Read-only, low-cost lead arrival heartbeat for approved management/QC."""
from datetime import datetime, time, timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from .models import ReferralLead
from .quality_command_views import _qc_scope


def _monitor_window(now):
    """08:00 through next-day 01:00, with the 01:00-08:00 break excluded."""
    local = timezone.localtime(now)
    clock = local.time().replace(tzinfo=None)
    active = clock >= time(8, 0) or clock < time(1, 0)
    date = local.date() if clock >= time(8, 0) else local.date() - timedelta(days=1)
    opened = timezone.make_aware(datetime.combine(date, time(8, 0)), timezone.get_current_timezone())
    return active, opened


@login_required
@require_GET
def live_last_lead(request):
    profile = getattr(request.user, "profile", None)
    if not request.user.is_active or (profile and not profile.is_active):
        raise PermissionDenied
    # The same access and branch restrictions as the QC command centre.
    branch_id = _qc_scope(request.user)
    qs = ReferralLead.objects.all()
    if branch_id:
        qs = qs.filter(assigned_to__branch_id=branch_id)
    # Primary-key ordering avoids a full timestamp sort on every poll.\n    recent = qs.order_by("-pk").values("id", "created_at").first()
    now = timezone.now()
    active, started = _monitor_window(now)
    last = recent["created_at"] if recent else None
    # For the warning, do not count overnight quiet hours before 08:00.
    effective = max(last, started) if last else started
    elapsed = max(0, int((now - effective).total_seconds())) if active else None
    response = JsonResponse({
        "ok": True, "server_time": now.isoformat(),
        "last_lead_at": last.isoformat() if last else None,
        "last_lead_id": recent["id"] if recent else None,
        "elapsed_seconds": elapsed,
        "monitoring": active, "alert": active and elapsed >= 3600,
        "threshold_minutes": 60,
    })
    response["Cache-Control"] = "private, no-store"
    return response
