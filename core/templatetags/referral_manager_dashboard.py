from datetime import timedelta

from django import template
from django.db.models import Q
from django.utils import timezone

from core.models import ReferralLead, ReferralProfile

register = template.Library()


def _manager_profiles(user):
    qs = ReferralProfile.objects.filter(is_active=True).exclude(
        user__profile__role='call_center'
    ).select_related(
        'user', 'user__profile', 'sponsor', 'sponsor__user', 'created_by'
    )
    role = getattr(getattr(user, 'profile', None), 'role', '')
    if role == 'manager' and not user.is_superuser:
        branch_id = getattr(getattr(user, 'profile', None), 'branch_id', None)
        qs = qs.filter(
            Q(user__profile__branch_id=branch_id)
            | Q(sponsor__user__profile__branch_id=branch_id)
            | Q(sponsor__sponsor__user__profile__branch_id=branch_id)
        ).distinct()
    return qs


def _empty_payload():
    today = timezone.localdate()
    start = today - timedelta(days=29)
    return {
        'member_today': 0,
        'member_month': 0,
        'lead_today': 0,
        'lead_month': 0,
        'activities': [],
        'recent_members_live': [],
        'top_recruiters': [],
        'chart_payload': {
            'labels': [(start + timedelta(days=i)).strftime('%m/%d') for i in range(30)],
            'members': [0] * 30,
            'leads': [0] * 30,
        },
    }


@register.inclusion_tag('core/referrals/_manager_live_dashboard.html', takes_context=True)
def referral_manager_live_dashboard(context):
    """Render the management live dashboard without ever taking the page down.

    The previous implementation used several complex aggregate queries. A runtime
    failure in this optional panel caused the entire referral dashboard to return
    HTTP 500, so this version deliberately favors simple, defensive queries and
    falls back to an empty live panel if data loading ever fails.
    """
    try:
        request = context.get('request')
        if request is None:
            return _empty_payload()

        profiles_qs = _manager_profiles(request.user)
        profile_ids = list(profiles_qs.values_list('id', flat=True))
        leads_qs = ReferralLead.objects.filter(referrer_id__in=profile_ids).select_related(
            'referrer', 'referrer__user', 'created_by'
        )

        today = timezone.localdate()
        month_start = today.replace(day=1)
        start = today - timedelta(days=29)
        days = [start + timedelta(days=i) for i in range(30)]
        day_index = {day: i for i, day in enumerate(days)}
        labels = [day.strftime('%m/%d') for day in days]
        member_series = [0] * 30
        lead_series = [0] * 30

        # Python-side grouping is intentionally used here. The live panel only
        # needs 30 days and this avoids database-specific date aggregation bugs.
        recent_profile_rows = list(
            profiles_qs.filter(created_at__date__gte=start).order_by('-created_at')
        )
        for profile in recent_profile_rows:
            local_day = timezone.localtime(profile.created_at).date()
            idx = day_index.get(local_day)
            if idx is not None:
                member_series[idx] += 1

        recent_lead_rows = list(
            leads_qs.filter(created_at__date__gte=start).order_by('-created_at')
        )
        for lead in recent_lead_rows:
            local_day = timezone.localtime(lead.created_at).date()
            idx = day_index.get(local_day)
            if idx is not None:
                lead_series[idx] += 1

        activities = []
        for member in recent_profile_rows[:8]:
            if member.user_id == request.user.id:
                continue
            creator = member.created_by.get_full_name() if member.created_by_id else ''
            activities.append({
                'kind': 'member',
                'title': f'عضو جدید: {member}',
                'detail': f'توسط {creator or "نامشخص"} · سطح {member.level}',
                'when': member.created_at,
            })
        for lead in recent_lead_rows[:8]:
            creator = lead.created_by.get_full_name() if lead.created_by_id else ''
            activities.append({
                'kind': 'lead',
                'title': f'لید جدید: {lead.full_name}',
                'detail': f'معرف: {lead.referrer} · ثبت‌کننده: {creator or "ورودی لینک/QR"}',
                'when': lead.created_at,
            })
        activities.sort(key=lambda item: item['when'], reverse=True)

        recent_members = list(
            profiles_qs.exclude(user=request.user).order_by('-created_at')[:10]
        )

        # Build ranking defensively; the network is small enough that this is
        # clearer and safer than a multi-join aggregate in the request path.
        ranking = []
        for person in list(profiles_qs.order_by('id')):
            person.new_members = ReferralProfile.objects.filter(
                sponsor=person, is_active=True
            ).exclude(user__profile__role='call_center').count()
            person.lead_total = ReferralLead.objects.filter(referrer=person).count()
            ranking.append(person)
        ranking.sort(key=lambda p: (p.new_members, p.lead_total), reverse=True)

        return {
            'member_today': sum(1 for p in recent_profile_rows if timezone.localtime(p.created_at).date() == today and p.user_id != request.user.id),
            'member_month': profiles_qs.filter(created_at__date__gte=month_start).exclude(user=request.user).count(),
            'lead_today': sum(1 for l in recent_lead_rows if timezone.localtime(l.created_at).date() == today),
            'lead_month': leads_qs.filter(created_at__date__gte=month_start).count(),
            'activities': activities[:10],
            'recent_members_live': recent_members,
            'top_recruiters': ranking[:6],
            'chart_payload': {
                'labels': labels,
                'members': member_series,
                'leads': lead_series,
            },
        }
    except Exception:
        return _empty_payload()
