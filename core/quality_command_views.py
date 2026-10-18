"""Read-only live quality command centre for authorized operations supervisors.

This dashboard reflects records in the app; it does not claim a live hardware
heartbeat, a CCTV integration, or PBX phone calls that the app does not store.
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import render
from django.template.loader import render_to_string
from django.utils import timezone

from .call_center_identity import call_center_display_name
from .device_booking_models import DeviceSessionBooking, PhysicalDevice
from .live_status_views import _visit_state
from .models import (
    Attendance, Branch, DeviceIssue, EmployeeProfile, LeaveRequest, ReferralLead,
    StaffNotification, Task, VisitAppointment,
)


def _qc_scope(user):
    profile = getattr(user, "profile", None)
    if not user.is_active or (profile and not profile.is_active):
        raise PermissionDenied("حساب کاربری فعال نیست.")
    if user.is_superuser or (profile and profile.role == "admin"):
        return None
    if profile and profile.role == "manager" and profile.branch_id:
        return profile.branch_id
    if profile and profile.role == "quality_control":
        return None
    if profile and profile.role == "internal_manager":
        return None
    title = (getattr(profile, "job_title", "") or "").strip().lower()
    if profile and (
        user.groups.filter(name="GreenLife QC").exists()
        or "کنترل کیفیت" in title
        or title in ("qc", "quality control")
    ):
        return None
    raise PermissionDenied("دسترسی به اتاق فرمان کنترل کیفیت ندارید.")


def _visit_detail(item, now):
    key, label, alert = _visit_state(item, now)
    return {
        "id": item.pk,
        "name": item.full_name,
        "time": item.appointment_time.strftime("%H:%M"),
        "service": item.service or "ویزیت",
        "label": label,
        "state": key,
        "alert": alert,
    }


def _physical_state(device, bookings, issues, now):
    """Never equate an app booking with an electronic device heartbeat."""
    if not device.is_active:
        return "inactive", "غیرفعال در برنامه", "", ""
    if device.name.strip().casefold() in issues:
        return "issue", "گزارش خرابی باز", "", ""
    related = [
        b for b in bookings
        if (b.device_id == device.pk or b.secondary_device_id == device.pk)
        and b.status not in ("cancelled", "rescheduled", "no_show")
    ]
    ongoing = next(
        (b for b in related
         if b.status in ("arrived", "late")
         and b.starts_at <= now < b.treatment_ends_at), None
    )
    if ongoing:
        return "busy", "جلسه ثبت‌شده", ongoing.appointment.full_name, (
            timezone.localtime(ongoing.treatment_ends_at).strftime("%H:%M")
        )
    pending = next(
        (b for b in related if b.status == "booked"
         and b.starts_at <= now < b.blocked_until), None
    )
    if pending:
        return "review", "نوبت شروع‌نشده", pending.appointment.full_name, (
            timezone.localtime(pending.starts_at).strftime("%H:%M")
        )
    future = sorted(
        (b for b in related if b.starts_at > now and b.status == "booked"),
        key=lambda b: b.starts_at,
    )
    if future:
        booking = future[0]
        return "reserved", "نوبت بعدی", booking.appointment.full_name, (
            timezone.localtime(booking.starts_at).strftime("%H:%M")
        )
    return "idle", "نوبت جاری ندارد", "", ""


def build_quality_snapshot(user):
    branch_scope = _qc_scope(user)
    today = timezone.localdate()
    now = timezone.now()
    local_now = timezone.localtime(now)
    # The retired Urmia center is off across active operations; Istanbul is
    # intentionally hidden in QC only until the owner requests its return.
    hidden_qc_branches = (
        Q(name__icontains="ارومیه") | Q(name__icontains="اروميه")
        | Q(name__icontains="urmia") | Q(name__icontains="orumi")
        | Q(name__icontains="استانبول") | Q(name__icontains="istanbul")
        | Q(country__code="TR")
    )
    branches = (
        Branch.objects.filter(is_active=True)
        .exclude(hidden_qc_branches)
        .order_by("name", "id")
    )
    if branch_scope:
        branches = branches.filter(pk=branch_scope)
    branch_list = list(branches)
    branch_ids = [b.pk for b in branch_list]

    visits = list(
        VisitAppointment.objects.filter(
            branch_id__in=branch_ids, appointment_date=today
        ).select_related("branch").order_by("branch_id", "appointment_time", "id")
    )
    devices = list(
        PhysicalDevice.objects.filter(branch_id__in=branch_ids)
        .select_related("branch", "device_type", "cabin")
        .order_by("branch_id", "name")
    )
    bookings = list(
        DeviceSessionBooking.objects.filter(
            branch_id__in=branch_ids, starts_at__date=today
        ).select_related("appointment", "device", "secondary_device")
        .order_by("starts_at", "id")
    )
    issues = list(
        DeviceIssue.objects.filter(
            branch_id__in=branch_ids
        ).exclude(status="resolved").order_by("-created_at")
    )
    attendance = list(
        Attendance.objects.filter(branch_id__in=branch_ids, date=today)
        .select_related("user")
    )
    staff = list(
        EmployeeProfile.objects.filter(
            branch_id__in=branch_ids, is_active=True, user__is_active=True,
            role__in=("admin", "internal_manager", "manager", "quality_control",
                      "employee", "call_center", "consultant", "doctor", "receptionist"),
        ).select_related("user")
    )
    # Only approved leave spanning today is a confirmed leave. Missing
    # check-in alone must not be represented as proven absenteeism.
    approved_leave_users = set(
        LeaveRequest.objects.filter(
            user_id__in=[p.user_id for p in staff],
            status="approved", start_date__lte=today, end_date__gte=today,
        ).values_list("user_id", flat=True)
    )
    task_counts = {
        row["assigned_to_id"]: row["n"]
        for row in Task.objects.filter(
            assigned_to_id__in=[p.user_id for p in staff],
            status="done", updated_at__date=today,
        ).values("assigned_to_id").annotate(n=Count("id"))
    }
    result = []
    for branch in branch_list:
        b_visits = [v for v in visits if v.branch_id == branch.pk]
        b_bookings = [b for b in bookings if b.branch_id == branch.pk]
        b_devices = [d for d in devices if d.branch_id == branch.pk]
        b_issues = [i for i in issues if i.branch_id == branch.pk]
        issue_names = {i.device_name.strip().casefold() for i in b_issues}
        b_attendance = [a for a in attendance if a.branch_id == branch.pk]
        b_staff = [p for p in staff if p.branch_id == branch.pk]
        attendance_map = {a.user_id: a for a in b_attendance}
        staff_rows = []
        for person in b_staff:
            record = attendance_map.get(person.user_id)
            status = (
                "late" if record and record.check_in and record.status == "late"
                else "present" if record and record.check_in and not record.check_out
                else "left" if record and record.check_out
                else "leave" if (record and record.status == "leave")
                    or person.user_id in approved_leave_users
                else "absent" if record and record.status == "absent"
                else "unregistered"
            )
            staff_rows.append({
                "name": person.user.get_full_name() or person.user.username,
                "role": person.job_title or person.get_role_display(),
                "state": status,
                "label": {
                    "late": "تأخیر ثبت‌شده",
                    "present": "حاضر",
                    "left": "خروج ثبت‌شده",
                    "leave": "مرخصی تأییدشده",
                    "absent": "غیبت ثبت‌شده",
                    "unregistered": "ورود ثبت نشده",
                }[status],
                "tasks_done": task_counts.get(person.user_id, 0),
                "check_in": (
                    timezone.localtime(record.check_in).strftime("%H:%M")
                    if record and record.check_in else ""
                ),
            })
        # Surface potential attendance issues before ordinary present rows.
        priority = {"absent": 0, "late": 1, "unregistered": 2, "leave": 3,
                    "present": 4, "left": 5}
        staff_rows.sort(key=lambda row: (priority.get(row["state"], 9), row["name"]))
        drows = []
        for device in b_devices:
            state, label, patient, next_time = _physical_state(
                device, b_bookings, issue_names, now
            )
            drows.append({
                "name": device.name,
                "cabin": device.cabin.name if device.cabin_id else "—",
                "state": state, "label": label,
                "patient": patient, "time": next_time,
            })
        result.append({
            "id": branch.pk, "name": branch.name,
            "visits_total": len(b_visits),
            "visits_done": sum(v.status in ("arrived", "completed") for v in b_visits),
            "visits_active": sum(v.status == "arrived" for v in b_visits),
            "visits_wait": sum(v.status == "booked" for v in b_visits),
            "visits_missed": sum(v.status in ("no_show", "cancelled") for v in b_visits),
            "visits": [_visit_detail(v, local_now) for v in b_visits[:150]],
            "visits_capped": len(b_visits) > 150,
            "devices": drows,
            "devices_total": len(drows),
            "devices_busy": sum(d["state"] == "busy" for d in drows),
            "issues": len(b_issues),
            "staff_total": len(b_staff),
            "staff": staff_rows,
            "staff_present": sum(row["state"] in ("present", "late") for row in staff_rows),
            "staff_late": sum(row["state"] == "late" for row in staff_rows),
            "staff_absent": sum(row["state"] == "absent" for row in staff_rows),
            "staff_leave": sum(row["state"] == "leave" for row in staff_rows),
            "staff_unregistered": sum(row["state"] == "unregistered" for row in staff_rows),
            "status": "attention" if (b_issues or any(
                row["state"] in ("late", "absent") for row in staff_rows
            )) else "normal",
        })

    # Use exactly the same visible operator scope for dashboard statistics
    # and drill-down: a branch manager must not see another site's leads.
    visible_call_center = EmployeeProfile.objects.filter(
        role="call_center", is_active=True, user__is_active=True,
        branch_id__in=branch_ids,
    ).select_related("user").order_by("user__first_name", "user__last_name", "pk")
    call_center = []
    # The CRM stores lead outcomes, not guaranteed PBX call-detail records.
    for p in visible_call_center:
        touches = ReferralLead.objects.filter(
            assigned_to=p, updated_at__date=today
        ).exclude(contact_result="")
        booked = VisitAppointment.objects.filter(
            created_by=p.user, created_at__date=today,
            source="call_center",
        ).exclude(status="cancelled").count()
        overdue = ReferralLead.objects.filter(
            assigned_to=p, next_follow_up__lt=today
        ).exclude(status__in=("won", "lost")).count()
        flower_name = call_center_display_name(p)
        # QC should never substitute a legal/real name for an unknown alias.
        real_name = p.user.get_full_name() or p.user.username
        if flower_name == real_name:
            flower_name = "گل تعیین‌نشده"
        call_center.append({
            "name": flower_name,
            "initial": flower_name[0],
            "avatar_url": p.avatar.url if p.avatar else "",
            "recorded": touches.count(),
            "booked": booked,
            "unanswered": touches.filter(contact_result="no_answer").count(),
            "overdue": overdue,
        })

    # The review queue is intentionally read-only. Counts remain exhaustive,
    # while only a bounded set of safe-to-display details is rendered.
    attention_issues = [
        {
            "id": issue.pk,
            "branch": next(
                (item.name for item in branch_list if item.pk == issue.branch_id),
                "—",
            ),
            "device": issue.device_name,
            "status": issue.get_status_display(),
            "date": timezone.localtime(issue.created_at).strftime("%Y/%m/%d"),
        }
        for issue in issues[:50]
    ]
    overdue_lead_qs = (
        ReferralLead.objects.filter(
            assigned_to__in=visible_call_center,
            next_follow_up__lt=today,
        ).exclude(status__in=("won", "lost"))
        .select_related("assigned_to__user")
        .order_by("next_follow_up", "id")
    )
    overdue_lead_total = overdue_lead_qs.count()
    attention_overdue = [
        {
            "name": lead.full_name,
            "operator": (
                call_center_display_name(lead.assigned_to)
                if call_center_display_name(lead.assigned_to)
                != (lead.assigned_to.user.get_full_name() or lead.assigned_to.user.username)
                else "گل تعیین‌نشده"
            ),
            "due_date": lead.next_follow_up.strftime("%Y/%m/%d"),
            "days": (today - lead.next_follow_up).days,
        }
        for lead in overdue_lead_qs[:75]
    ]

    all_notifications = StaffNotification.objects.filter(
        user=user, is_read=False
    ).order_by("-created_at")[:5]
    return {
        "generated_at": local_now.strftime("%H:%M:%S"),
        "date_label": today.strftime("%Y/%m/%d"),
        "branches": result,
        "call_center": call_center,
        "alerts": [
            {"title": i.title, "message": i.message[:160]}
            for i in all_notifications
        ],
        "total_visits": sum(x["visits_total"] for x in result),
        "total_arrived": sum(x["visits_done"] for x in result),
        "total_devices": sum(x["devices_total"] for x in result),
        "busy_devices": sum(x["devices_busy"] for x in result),
        "issue_count": sum(x["issues"] for x in result),
        "present_count": sum(x["staff_present"] for x in result),
        "recorded_contacts": sum(x["recorded"] for x in call_center),
        "bookings": sum(x["booked"] for x in call_center),
        "overdue_followups": sum(x["overdue"] for x in call_center),
        "attention_issues": attention_issues,
        "attention_issues_more": max(0, len(issues) - len(attention_issues)),
        "attention_overdue": attention_overdue,
        "attention_overdue_more": max(0, overdue_lead_total - len(attention_overdue)),
        "limited_branch": bool(branch_scope),
    }


@login_required
def quality_command_center(request):
    snapshot = build_quality_snapshot(request.user)
    response = render(
        request, "core/quality_command_center.html", {"snapshot": snapshot}
    )
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
def quality_command_data(request):
    snapshot = build_quality_snapshot(request.user)
    html = render_to_string(
        "core/_quality_command_content.html",
        {"snapshot": snapshot}, request=request,
    )
    response = JsonResponse({
        "ok": True,
        "html": html,
        "generated_at": snapshot["generated_at"],
    }, json_dumps_params={"ensure_ascii": False})
    response["Cache-Control"] = "private, no-store"
    return response
