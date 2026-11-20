from urllib.parse import urlencode

from django.db.models import Count
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .all_leads_views import management_required
from .call_center_identity import call_center_display_name
from .lead_management_views import OPEN_STATUSES, _lead_hub_queryset
from .models import Attendance, EmployeeProfile, LeaveRequest, ReferralLead


FLOWER_ART = {
    'نرگس': 'narges', 'بنفشه': 'banafsheh', 'یاسمن': 'yasaman',
    'خورشیدی': 'khorshidi', 'لاله': 'laleh', 'کاملیا': 'camellia',
}


def queue_url(**filters):
    return reverse('management_all_leads') + '?' + urlencode({'state': 'open', **filters})


def attendance_status(attendance, on_leave, now):
    if on_leave:
        return 'inactive', 'مرخصی'
    if attendance is None or not attendance.check_in or attendance.check_in > now:
        return 'inactive', 'ورود ثبت نشده'
    if attendance.check_out:
        return 'inactive', 'خروج ثبت شده'
    if attendance.break_started_at:
        return 'pause', 'در وقفه'
    return 'present', 'حاضر'


def reservoir_context(request):
    now = timezone.localtime()
    leads = _lead_hub_queryset(request, ReferralLead.objects.all()).filter(status__in=OPEN_STATUSES)
    # The reservoir and every flower use the same database snapshot, so one
    # assignment cannot appear in both places during the same page load.
    counts = dict(leads.order_by().values('assigned_to_id')
                  .annotate(count=Count('pk')).values_list('assigned_to_id', 'count'))
    total = sum(counts.values())
    unassigned = counts.get(None, 0)
    profiles = list(EmployeeProfile.objects.filter(
        role='call_center', is_active=True, user__is_active=True,
    ).select_related('user').order_by('pk'))
    user_ids = [profile.user_id for profile in profiles]
    attendance = {
        row.user_id: row for row in Attendance.objects.filter(user_id__in=user_ids, date=now.date())
    }
    leave_ids = set(LeaveRequest.objects.filter(
        user_id__in=user_ids, status='approved', start_date__lte=now.date(), end_date__gte=now.date(),
    ).values_list('user_id', flat=True))
    flowers = []
    for profile in profiles:
        name = call_center_display_name(profile)
        tone, label = attendance_status(attendance.get(profile.user_id), profile.user_id in leave_ids, now)
        flowers.append({
            'name': name, 'art': FLOWER_ART.get(name, 'default'),
            'tone': tone, 'status': label, 'count': counts.get(profile.pk, 0),
            'url': queue_url(flower=profile.pk),
        })
    return {
        'unassigned': unassigned, 'total': total,
        'fill': round(100 * unassigned / total) if total else 0,
        'unassigned_url': queue_url(flower='none'),
        'refreshed': now,
        'flowers': flowers,
    }


@never_cache
@require_GET
@management_required
def command_room(request):
    return render(request, 'core/command_room.html', reservoir_context(request))
