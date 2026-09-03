from datetime import timedelta

from django import template
from django.db.models import Count, Q
from django.db.models.functions import TruncDate
from django.utils import timezone

from core.models import ReferralLead, ReferralProfile

register = template.Library()


def _manager_profiles(user):
    qs = ReferralProfile.objects.filter(is_active=True).exclude(
        user__profile__role='call_center'
    ).select_related('user', 'user__profile', 'sponsor__user', 'created_by')
    role = getattr(getattr(user, 'profile', None), 'role', '')
    if role == 'manager':
        branch_id = getattr(getattr(user, 'profile', None), 'branch_id', None)
        qs = qs.filter(
            Q(user__profile__branch_id=branch_id)
            | Q(sponsor__user__profile__branch_id=branch_id)
            | Q(sponsor__sponsor__user__profile__branch_id=branch_id)
        ).distinct()
    return qs


@register.inclusion_tag('core/referrals/_manager_live_dashboard.html', takes_context=True)
def referral_manager_live_dashboard(context):
    request = context['request']
    profiles = _manager_profiles(request.user)
    profile_ids = list(profiles.values_list('id', flat=True))
    leads = ReferralLead.objects.filter(referrer_id__in=profile_ids).select_related(
        'referrer__user', 'created_by'
    )

    today = timezone.localdate()
    month_start = today.replace(day=1)
    start = today - timedelta(days=29)

    member_daily = {
        row['day']: row['count']
        for row in profiles.filter(created_at__date__gte=start)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(count=Count('id'))
    }
    lead_daily = {
        row['day']: row['count']
        for row in leads.filter(created_at__date__gte=start)
        .annotate(day=TruncDate('created_at'))
        .values('day')
        .annotate(count=Count('id'))
    }

    labels, member_series, lead_series = [], [], []
    for offset in range(30):
        day = start + timedelta(days=offset)
        labels.append(day.strftime('%m/%d'))
        member_series.append(member_daily.get(day, 0))
        lead_series.append(lead_daily.get(day, 0))

    activities = []
    for member in profiles.order_by('-created_at')[:8]:
        if member.user_id == request.user.id:
            continue
        creator = member.created_by.get_full_name() if member.created_by_id else ''
        activities.append({
            'kind': 'member',
            'title': f'عضو جدید: {member}',
            'detail': f'توسط {creator or "نامشخص"} · سطح {member.level}',
            'when': member.created_at,
        })
    for lead in leads.order_by('-created_at')[:8]:
        creator = lead.created_by.get_full_name() if lead.created_by_id else ''
        activities.append({
            'kind': 'lead',
            'title': f'لید جدید: {lead.full_name}',
            'detail': f'معرف: {lead.referrer} · ثبت‌کننده: {creator or "ورودی لینک/QR"}',
            'when': lead.created_at,
        })
    activities.sort(key=lambda item: item['when'], reverse=True)

    recent_members = profiles.exclude(user=request.user).order_by('-created_at')[:10]
    top_recruiters = profiles.annotate(
        new_members=Count('members', filter=Q(members__is_active=True), distinct=True),
        lead_total=Count('leads', distinct=True),
    ).order_by('-new_members', '-lead_total')[:6]

    return {
        'member_today': profiles.filter(created_at__date=today).exclude(user=request.user).count(),
        'member_month': profiles.filter(created_at__date__gte=month_start).exclude(user=request.user).count(),
        'lead_today': leads.filter(created_at__date=today).count(),
        'lead_month': leads.filter(created_at__date__gte=month_start).count(),
        'activities': activities[:10],
        'recent_members_live': recent_members,
        'top_recruiters': top_recruiters,
        'chart_payload': {
            'labels': labels,
            'members': member_series,
            'leads': lead_series,
        },
    }
