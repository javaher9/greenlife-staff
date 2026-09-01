from datetime import timedelta
from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from .models import Attendance, DailyReport, StaffNotification, Task, ChecklistCompletion, ChecklistTemplate
from .operations import auto_kpi, attendance_status_for, approved_leave, shift_rule


def manager_users_for_branch(branch):
    qs = User.objects.filter(profile__is_active=True, profile__role__in=("admin", "internal_manager", "manager"))
    if branch:
        qs = qs.filter(
            Q(profile__role__in=("admin", "internal_manager")) |
            Q(profile__role="manager", profile__branch=branch)
        )
    return qs.distinct()


def notify_once(user, title, message, notification_type, related_date):
    exists = StaffNotification.objects.filter(
        user=user,
        title=title,
        notification_type=notification_type,
        related_date=related_date,
        message=message,
    ).exists()
    if exists:
        return False
    StaffNotification.objects.create(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        related_date=related_date,
    )
    return True


def _full_name(user):
    return user.get_full_name() or user.username


def generate_smart_alerts(day=None):
    """Create deduplicated operational alerts. Safe to run repeatedly."""
    day = day or timezone.localdate()
    now = timezone.localtime()
    created = 0

    users = User.objects.filter(profile__is_active=True).select_related("profile", "profile__branch")
    for user in users:
        branch = user.profile.branch
        leave = approved_leave(user, day)
        if leave:
            continue

        rec = Attendance.objects.filter(user=user, date=day).first()
        rule = shift_rule(user, day)

        # Late arrival: notify employee and managers as soon as it is known.
        if rec and rec.check_in:
            status = attendance_status_for(user, day, rec.check_in)
            if status == "late":
                t = timezone.localtime(rec.check_in).strftime("%H:%M")
                msg_user = f"ورود امروز شما ساعت {t} با تأخیر ثبت شده است."
                created += int(notify_once(user, "ثبت تأخیر امروز", msg_user, "late_arrival", day))
                msg_mgr = f"{_full_name(user)} امروز ساعت {t} با تأخیر وارد شده است."
                for mgr in manager_users_for_branch(branch):
                    created += int(notify_once(mgr, "تأخیر پرسنل", msg_mgr, "late_arrival_manager", day))

        # Not checked in after scheduled start + grace + 30 minutes.
        elif rule.get("start"):
            threshold = timezone.make_aware(
                timezone.datetime.combine(day, rule["start"]),
                timezone.get_current_timezone(),
            ) + timedelta(minutes=rule.get("grace", 0) + 30)
            if now >= threshold:
                msg_mgr = f"{_full_name(user)} تا این لحظه ورود امروز را ثبت نکرده است."
                for mgr in manager_users_for_branch(branch):
                    created += int(notify_once(mgr, "عدم ثبت ورود", msg_mgr, "missing_checkin", day))


        # Required daily checklist incomplete after shift end + 30 minutes.
        if rule.get("end"):
            end_threshold = timezone.make_aware(
                timezone.datetime.combine(day, rule["end"]),
                timezone.get_current_timezone(),
            ) + timedelta(minutes=30)
            if now >= end_threshold:
                p=user.profile
                templates=ChecklistTemplate.objects.filter(is_active=True).filter(
                    Q(branch__isnull=True)|Q(branch=p.branch)
                ).filter(Q(role='')|Q(role=p.role)).filter(
                    Q(job_title='')|Q(job_title=p.job_title)
                ).prefetch_related('items').distinct()
                required_items=[i for t in templates for i in t.items.all() if i.is_required]
                if required_items:
                    done_ids=set(ChecklistCompletion.objects.filter(user=user,date=day,is_done=True,item__in=required_items).values_list("item_id",flat=True))
                    missing=[i for i in required_items if i.id not in done_ids]
                    if missing:
                        msg_user=f"چک‌لیست امروز شما {len(missing)} مورد اجباری انجام‌نشده دارد."
                        created += int(notify_once(user,"چک‌لیست ناقص",msg_user,"checklist_incomplete",day))
                        msg_mgr=f"{_full_name(user)} امروز {len(missing)} مورد اجباری چک‌لیست را انجام نداده است."
                        for mgr in manager_users_for_branch(branch):
                            created += int(notify_once(mgr,"چک‌لیست ناقص پرسنل",msg_mgr,"checklist_incomplete_manager",day))

    # Overdue tasks: employee + branch managers.
    overdue = Task.objects.filter(status__in=("todo", "doing"), due_date__lt=day).select_related(
        "assigned_to", "assigned_to__profile", "assigned_to__profile__branch"
    )
    for task in overdue:
        user = task.assigned_to
        branch = getattr(user.profile, "branch", None)
        msg_user = f'وظیفه «{task.title}» از موعد خود گذشته و هنوز تکمیل نشده است.'
        created += int(notify_once(user, "وظیفه عقب‌افتاده", msg_user, "overdue_task", day))
        msg_mgr = f'{_full_name(user)} وظیفه عقب‌افتاده دارد: «{task.title}».'
        for mgr in manager_users_for_branch(branch):
            created += int(notify_once(mgr, "Task عقب‌افتاده", msg_mgr, "overdue_task_manager", day))

    # KPI drop: compare latest 30 days with previous 30 days; alert when meaningful.
    current_end = day
    current_start = day - timedelta(days=29)
    prev_end = current_start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=29)
    for user in users:
        current = auto_kpi(user, current_start, current_end)["score"]
        previous = auto_kpi(user, prev_start, prev_end)["score"]
        drop = previous - current
        if current < 70 and drop >= 10:
            msg_user = f"KPI سی‌روزه شما به {current} رسیده و نسبت به دوره قبل {drop} امتیاز افت کرده است."
            created += int(notify_once(user, "افت KPI", msg_user, "kpi_drop", day))
            msg_mgr = f"KPI {_full_name(user)} به {current} رسیده و {drop} امتیاز نسبت به دوره قبل افت کرده است."
            for mgr in manager_users_for_branch(user.profile.branch):
                created += int(notify_once(mgr, "هشدار افت KPI", msg_mgr, "kpi_drop_manager", day))

    return created
