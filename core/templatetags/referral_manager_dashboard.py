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
    ).select_related(
        'user', 'user__profile',
        'sponsor__user', 'sponsor__user__profile',
        'created_by', 'created_by__profile',
    )
    role = getattr(getattr(user, 'profile', None), 'role', '')
    if role == 'manager':
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
    return _image_url(profile.display_photo) if profile else ''


def _user_avatar(user):
    return _image_url(getattr(getattr(user, 'profile', None), 'avatar', None)) if user else ''


@register.inclusion_tag('core/referrals/_manager_live_dashboard.html', takes_context=True)
def referral_manager_live_dashboard(context):
    request = context['request']
    profiles = _manager_profiles(request.user)
    profile_ids = list(profiles.values_list('id', flat=True))
    leads = ReferralLead.objects.filter(referrer_id__in=profile_ids).select_related(
        'referrer__user', 'referrer__user__profile', 'created_by', 'created_by__profile'
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
            'avatar': _profile_avatar(member),
            'initial': (member.user.first_name or member.user.last_name or '?')[:1],
        })
    for lead in leads.order_by('-created_at')[:8]:
        creator = lead.created_by.get_full_name() if lead.created_by_id else ''
        activities.append({
            'kind': 'lead',
            'title': f'لید جدید: {lead.full_name}',
            'detail': f'معرف: {lead.referrer} · ثبت‌کننده: {creator or "ورودی لینک/QR"}',
            'when': lead.created_at,
            'avatar': _profile_avatar(lead.referrer),
            'initial': (lead.referrer.user.first_name or lead.referrer.user.last_name or '?')[:1],
        })
    activities.sort(key=lambda item: item['when'], reverse=True)

    recent_members = profiles.exclude(user=request.user).order_by('-created_at')[:10]
    top_recruiters = profiles.annotate(
        new_members=Count('members', filter=Q(members__is_active=True), distinct=True),
        lead_total=Count('leads', distinct=True),
    ).order_by('-new_members', '-lead_total')[:6]

    recent_member_rows = []
    for member in recent_members:
        sponsor = member.sponsor
        actor = sponsor.user if sponsor else member.created_by
        recent_member_rows.append({
            'profile': member,
            'avatar': _profile_avatar(member),
            'initial': (member.user.first_name or member.user.last_name or '?')[:1],
            'actor_name': (
                str(sponsor) if sponsor else
                (member.created_by.get_full_name() if member.created_by_id else '—')
            ),
            'actor_avatar': _profile_avatar(sponsor) if sponsor else _user_avatar(member.created_by),
            'actor_initial': (
                ((actor.first_name or actor.last_name or '?')[:1]) if actor else '—'
            ),
        })

    top_recruiter_rows = []
    for person in top_recruiters:
        top_recruiter_rows.append({
            'profile': person,
            'avatar': _profile_avatar(person),
            'initial': (person.user.first_name or person.user.last_name or '?')[:1],
            'new_members': person.new_members,
            'lead_total': person.lead_total,
        })

    return {
        'member_today': profiles.filter(created_at__date=today).exclude(user=request.user).count(),
        'member_month': profiles.filter(created_at__date__gte=month_start).exclude(user=request.user).count(),
        'lead_today': leads.filter(created_at__date=today).count(),
        'lead_month': leads.filter(created_at__date__gte=month_start).count(),
        'activities': activities[:10],
        'recent_member_rows': recent_member_rows,
        'top_recruiter_rows': top_recruiter_rows,
        'chart_payload': {
            'labels': labels,
            'members': member_series,
            'leads': lead_series,
        },
    }
