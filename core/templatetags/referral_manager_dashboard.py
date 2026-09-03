from datetime import timedelta

from django import template
from django.db.models import Q
from django.utils import timezone

from core.models import ReferralLead, ReferralProfile
from public_network.models import PublicNetworkMember

register = template.Library()


def _manager_profiles(user):
    qs = ReferralProfile.objects.filter(is_active=True).exclude(
        user__profile__role='call_center'
    ).select_related(
        'user', 'user__profile',
        'sponsor', 'sponsor__user', 'sponsor__user__profile',
        'created_by', 'created_by__profile',
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


def _image_url(image):
    try:
        return image.url if image else ''
    except Exception:
        return ''


def _profile_avatar(profile):
    if not profile:
        return ''
    try:
        return _image_url(profile.display_photo)
    except Exception:
        return ''


def _user_avatar(user):
    if not user:
        return ''
    try:
        return _image_url(getattr(getattr(user, 'profile', None), 'avatar', None))
    except Exception:
        return ''


def _initial(user):
    if not user:
        return '?'
    return (user.first_name or user.last_name or user.username or '?')[:1]


def _public_network_summary():
    today = timezone.localdate()
    month_start = today.replace(day=1)
    qs = PublicNetworkMember.objects.filter(is_active=True)
    latest = qs.select_related('user', 'sponsor__user').order_by('-created_at')[:4]
    return {
        'public_total': qs.count(),
        'public_today': qs.filter(created_at__date=today).count(),
        'public_month': qs.filter(created_at__date__gte=month_start).count(),
        'public_story': qs.filter(source='story').count(),
        'public_latest': latest,
    }


def _empty_payload():
    today = timezone.localdate()
    start = today - timedelta(days=29)
    payload = {
        'member_today': 0,
        'member_month': 0,
        'lead_today': 0,
        'lead_month': 0,
        'activities': [],
        'recent_member_rows': [],
        'top_recruiter_rows': [],
        'chart_payload': {
            'labels': [(start + timedelta(days=i)).strftime('%m/%d') for i in range(30)],
            'members': [0] * 30,
            'leads': [0] * 30,
        },
        'public_total': 0,
        'public_today': 0,
        'public_month': 0,
        'public_story': 0,
        'public_latest': [],
    }
    try:
        payload.update(_public_network_summary())
    except Exception:
        pass
    return payload


@register.inclusion_tag('core/referrals/_manager_live_dashboard.html', takes_context=True)
def referral_manager_live_dashboard(context):
    """Render the management live dashboard defensively with person avatars."""
    try:
        request = context.get('request')
        if request is None:
            return _empty_payload()

        profiles_qs = _manager_profiles(request.user)
        profile_ids = list(profiles_qs.values_list('id', flat=True))
        leads_qs = ReferralLead.objects.filter(referrer_id__in=profile_ids).select_related(
            'referrer', 'referrer__user', 'referrer__user__profile',
            'created_by', 'created_by__profile'
        )

        today = timezone.localdate()
        month_start = today.replace(day=1)
        start = today - timedelta(days=29)
        days = [start + timedelta(days=i) for i in range(30)]
        day_index = {day: i for i, day in enumerate(days)}
        labels = [day.strftime('%m/%d') for day in days]
        member_series = [0] * 30
        lead_series = [0] * 30

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
                'avatar': _profile_avatar(member),
                'initial': _initial(member.user),
            })
        for lead in recent_lead_rows[:8]:
            creator = lead.created_by.get_full_name() if lead.created_by_id else ''
            activities.append({
                'kind': 'lead',
                'title': f'لید جدید: {lead.full_name}',
                'detail': f'معرف: {lead.referrer} · ثبت‌کننده: {creator or "ورودی لینک/QR"}',
                'when': lead.created_at,
                'avatar': _profile_avatar(lead.referrer),
                'initial': _initial(lead.referrer.user),
            })
        activities.sort(key=lambda item: item['when'], reverse=True)

        recent_members = list(
            profiles_qs.exclude(user=request.user).order_by('-created_at')[:10]
        )
        recent_member_rows = []
        for member in recent_members:
            sponsor = member.sponsor
            actor = sponsor.user if sponsor else member.created_by
            recent_member_rows.append({
                'profile': member,
                'avatar': _profile_avatar(member),
                'initial': _initial(member.user),
                'actor_name': (
                    str(sponsor) if sponsor else
                    (member.created_by.get_full_name() if member.created_by_id else '—')
                ),
                'actor_avatar': _profile_avatar(sponsor) if sponsor else _user_avatar(member.created_by),
                'actor_initial': _initial(actor) if actor else '—',
            })

        ranking = []
        for person in list(profiles_qs.order_by('id')):
            new_members = ReferralProfile.objects.filter(
                sponsor=person, is_active=True
            ).exclude(user__profile__role='call_center').count()
            lead_total = ReferralLead.objects.filter(referrer=person).count()
            ranking.append((person, new_members, lead_total))
        ranking.sort(key=lambda row: (row[1], row[2]), reverse=True)
        top_recruiter_rows = [
            {
                'profile': person,
                'avatar': _profile_avatar(person),
                'initial': _initial(person.user),
                'new_members': new_members,
                'lead_total': lead_total,
            }
            for person, new_members, lead_total in ranking[:6]
        ]

        payload = {
            'member_today': sum(1 for p in recent_profile_rows if timezone.localtime(p.created_at).date() == today and p.user_id != request.user.id),
            'member_month': profiles_qs.filter(created_at__date__gte=month_start).exclude(user=request.user).count(),
            'lead_today': sum(1 for l in recent_lead_rows if timezone.localtime(l.created_at).date() == today),
            'lead_month': leads_qs.filter(created_at__date__gte=month_start).count(),
            'activities': activities[:10],
            'recent_member_rows': recent_member_rows,
            'top_recruiter_rows': top_recruiter_rows,
            'chart_payload': {
                'labels': labels,
                'members': member_series,
                'leads': lead_series,
            },
        }
        payload.update(_public_network_summary())
        return payload
    except Exception:
        return _empty_payload()
