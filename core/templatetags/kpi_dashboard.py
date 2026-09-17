from collections import defaultdict
from datetime import timedelta

from django import template
from django.db.models import Count, Q
from django.utils import timezone

from core.models import Attendance, Branch, DailyReport, EmployeeProfile, KPIRecord, ReferralLead, Task
from core.jalali import format_jalali

register = template.Library()

BEHAVIOR_TERMS = ('رفتار', 'اخلاق', 'همکاری', 'تعامل', 'حرفه')
DISCIPLINE_TERMS = ('نظم', 'حضور', 'تعهد', 'وقت')
GROWTH_TERMS = ('رشد', 'یادگیری', 'ابتکار', 'توسعه')


def _avg(values):
    values = [float(v) for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _status(score):
    if score is None:
        return ('در انتظار', 'pending')
    if score >= 90:
        return ('عالی', 'excellent')
    if score >= 80:
        return ('خوب', 'good')
    if score >= 70:
        return ('متوسط', 'average')
    return ('نیازمند توجه', 'danger')


def _period(request):
    today = timezone.localdate()
    key = (request.GET.get('period') or 'month').strip()
    if key == 'week':
        start = today - timedelta(days=6)
        label = '۷ روز اخیر'
    elif key == 'quarter':
        start = today - timedelta(days=89)
        label = '۹۰ روز اخیر'
    else:
        key = 'month'
        start = today.replace(day=1)
        label = 'ماه جاری'
    return key, start, today, label


def _record_bucket(records):
    result = defaultdict(list)
    for rec in records:
        result[rec.user_id].append(rec)
    return result


def _term_score(records, terms):
    return _avg([r.score for r in records if any(term in (r.title or '') for term in terms)])


@register.simple_tag
def kpi_dashboard(request):
    period_key, start, end, period_label = _period(request)
    role_filter = (request.GET.get('role') or '').strip()
    branch_filter = (request.GET.get('branch') or '').strip()
    query = (request.GET.get('q') or '').strip()

    profiles = EmployeeProfile.objects.filter(is_active=True, user__is_active=True).exclude(role='referrer').select_related('user', 'branch')
    user_role = getattr(getattr(request.user, 'profile', None), 'role', '')
    if user_role == 'manager' and getattr(request.user.profile, 'branch_id', None):
        profiles = profiles.filter(branch=request.user.profile.branch)
    if role_filter:
        profiles = profiles.filter(role=role_filter)
    if branch_filter.isdigit():
        profiles = profiles.filter(branch_id=int(branch_filter))
    if query:
        profiles = profiles.filter(
            Q(user__first_name__icontains=query) |
            Q(user__last_name__icontains=query) |
            Q(user__username__icontains=query) |
            Q(job_title__icontains=query)
        )
    profiles = list(profiles.order_by('branch__name', 'user__last_name', 'user__first_name', 'user__username'))
    user_ids = [p.user_id for p in profiles]
    profile_ids = [p.id for p in profiles]

    records = KPIRecord.objects.filter(user_id__in=user_ids, period_start__lte=end, period_end__gte=start).order_by('-period_end', '-created_at')
    record_map = _record_bucket(records)

    attendance_map = {row['user_id']: row for row in Attendance.objects.filter(user_id__in=user_ids, date__range=(start, end)).values('user_id').annotate(
        total=Count('id'), present=Count('id', filter=Q(status='present')), late=Count('id', filter=Q(status='late')), absent=Count('id', filter=Q(status='absent'))
    )}
    task_map = {row['assigned_to_id']: row for row in Task.objects.filter(assigned_to_id__in=user_ids, due_date__range=(start, end)).values('assigned_to_id').annotate(
        total=Count('id'), done=Count('id', filter=Q(status='done'))
    )}
    report_map = {row['user_id']: row['count'] for row in DailyReport.objects.filter(user_id__in=user_ids, created_at__date__range=(start, end)).values('user_id').annotate(count=Count('created_at__date', distinct=True))}
    lead_map = {row['assigned_to_id']: row for row in ReferralLead.objects.filter(assigned_to_id__in=profile_ids, created_at__date__range=(start, end)).values('assigned_to_id').annotate(
        total=Count('id'), contacted=Count('id', filter=Q(status__in=('contacted', 'appointment', 'visited', 'won', 'lost'))), appointments=Count('id', filter=Q(status__in=('appointment', 'visited', 'won'))), won=Count('id', filter=Q(status='won'))
    )}

    rows = []
    for profile in profiles:
        recs = record_map.get(profile.user_id, [])
        manual_all = _avg([r.score for r in recs])
        behavior = _term_score(recs, BEHAVIOR_TERMS)
        discipline_manual = _term_score(recs, DISCIPLINE_TERMS)
        growth = _term_score(recs, GROWTH_TERMS)

        att = attendance_map.get(profile.user_id, {})
        att_total = att.get('total', 0) or 0
        discipline_auto = None
        if att_total:
            discipline_auto = round(((att.get('present', 0) or 0) + (att.get('late', 0) or 0) * .5) * 100 / att_total, 1)
        discipline = discipline_manual if discipline_manual is not None else discipline_auto

        task = task_map.get(profile.user_id, {})
        task_total = task.get('total', 0) or 0
        task_score = round((task.get('done', 0) or 0) * 100 / task_total, 1) if task_total else None
        performance = manual_all
        lead = lead_map.get(profile.id, {})
        if profile.role == 'call_center' and (lead.get('total', 0) or 0):
            total = lead['total']
            contact_rate = lead.get('contacted', 0) * 100 / total
            appointment_rate = lead.get('appointments', 0) * 100 / total
            won_rate = lead.get('won', 0) * 100 / total
            performance = round(contact_rate * .45 + appointment_rate * .35 + min(100, won_rate * 4) * .20, 1)
        elif performance is None and task_score is not None:
            performance = task_score

        weighted = []
        for value, weight in ((performance, 50), (behavior, 25), (discipline, 15), (growth, 10)):
            if value is not None:
                weighted.append((value, weight))
        overall = round(sum(v * w for v, w in weighted) / sum(w for _, w in weighted), 1) if weighted else None
        completion = sum(w for _, w in weighted)
        label, status_class = _status(overall)
        full_name = profile.user.get_full_name() or profile.user.username
        rows.append({
            'profile': profile, 'profile_id': profile.id, 'name': full_name,
            'role': profile.get_role_display(), 'role_key': profile.role,
            'branch': profile.branch.name if profile.branch else 'بدون شعبه',
            'job_title': profile.job_title or profile.get_role_display(),
            'score': overall, 'performance': performance, 'behavior': behavior,
            'discipline': discipline, 'growth': growth, 'completion': completion,
            'status': label, 'status_class': status_class,
            'reports': report_map.get(profile.user_id, 0),
            'leads': lead.get('total', 0) or 0,
            'appointments': lead.get('appointments', 0) or 0,
            'won': lead.get('won', 0) or 0,
        })

    ranked = sorted(rows, key=lambda r: (r['score'] is not None, r['score'] or -1), reverse=True)
    for idx, row in enumerate(ranked, 1):
        row['rank'] = idx if row['score'] is not None else None

    scored = [r for r in ranked if r['score'] is not None]
    overall = _avg([r['score'] for r in scored])
    best = scored[0] if scored else None
    behavioral = sorted([r for r in rows if r['behavior'] is not None], key=lambda r: r['behavior'], reverse=True)
    best_behavior = behavioral[0] if behavioral else None
    attention = [r for r in rows if (r['score'] is not None and r['score'] < 70) or r['completion'] < 50]

    criteria = {
        'performance': _avg([r['performance'] for r in rows]),
        'behavior': _avg([r['behavior'] for r in rows]),
        'discipline': _avg([r['discipline'] for r in rows]),
        'growth': _avg([r['growth'] for r in rows]),
    }
    role_rows = []
    for role_key, role_label in EmployeeProfile.ROLE_CHOICES:
        role_scores = [r['score'] for r in rows if r['role_key'] == role_key and r['score'] is not None]
        if role_scores:
            role_rows.append({'key': role_key, 'label': role_label, 'score': _avg(role_scores), 'count': len(role_scores)})
    role_rows.sort(key=lambda r: r['score'], reverse=True)

    completed = len([r for r in rows if r['completion'] >= 75])
    partial = len([r for r in rows if 0 < r['completion'] < 75])
    missing = len([r for r in rows if r['completion'] == 0])
    total_people = len(rows)
    completion_percent = round(completed * 100 / total_people) if total_people else 0

    trend = []
    for offset in range(5, -1, -1):
        t_end = end - timedelta(days=offset * 30)
        t_start = t_end - timedelta(days=29)
        scores = list(KPIRecord.objects.filter(user_id__in=user_ids, period_start__lte=t_end, period_end__gte=t_start).values_list('score', flat=True))
        value = _avg(scores) or 0
        trend.append({'value': value, 'height': max(14, min(100, round(value)))})

    branches = Branch.objects.filter(is_active=True).order_by('name')
    roles = [(key, label) for key, label in EmployeeProfile.ROLE_CHOICES if key != 'referrer']
    return {
        'rows': ranked, 'top': ranked[:5], 'overall': overall, 'best': best,
        'best_behavior': best_behavior, 'attention_count': len(attention),
        'criteria': criteria, 'role_rows': role_rows[:6], 'completed': completed,
        'partial': partial, 'missing': missing, 'completion_percent': completion_percent,
        'period_key': period_key, 'period_label': period_label,
        'period_range': f'{format_jalali(start)} تا {format_jalali(end)}',
        'branches': branches, 'roles': roles, 'branch_filter': branch_filter,
        'role_filter': role_filter, 'query': query, 'trend': trend,
    }
