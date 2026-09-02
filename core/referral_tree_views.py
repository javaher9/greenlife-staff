import uuid

from django.contrib.auth.decorators import login_required
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, render

from .models import ReferralProfile, ReferralSale


def _role(user):
    role = getattr(getattr(user, 'profile', None), 'role', 'employee')
    return 'admin' if role == 'internal_manager' else role


def _ensure_profile(user):
    profile = ReferralProfile.objects.filter(user=user).first()
    if profile:
        return profile
    code = f'GL{uuid.uuid4().hex[:8].upper()}'
    while ReferralProfile.objects.filter(referral_code=code).exists():
        code = f'GL{uuid.uuid4().hex[:8].upper()}'
    return ReferralProfile.objects.create(
        user=user,
        referral_code=code,
        phone=getattr(getattr(user, 'profile', None), 'phone', ''),
        created_by=user,
    )


def _visible_profiles(request, current):
    qs = ReferralProfile.objects.filter(is_active=True).exclude(
        user__profile__role='call_center'
    ).select_related('user', 'user__profile', 'sponsor', 'sponsor__user')

    role = _role(request.user)
    if role == 'manager':
        branch_id = getattr(getattr(request.user, 'profile', None), 'branch_id', None)
        return qs.filter(
            Q(user__profile__branch_id=branch_id)
            | Q(sponsor__user__profile__branch_id=branch_id)
            | Q(sponsor__sponsor__user__profile__branch_id=branch_id)
        ).distinct()
    if role == 'admin':
        return qs

    direct = list(current.members.filter(is_active=True).exclude(
        user__profile__role='call_center'
    ).values_list('id', flat=True))
    second = list(qs.filter(sponsor_id__in=direct).values_list('id', flat=True))
    return qs.filter(pk__in=[current.pk, *direct, *second])


def _photo_url(profile):
    image = profile.display_photo
    try:
        return image.url if image else ''
    except Exception:
        return ''


def _display_name(profile):
    name = (profile.user.get_full_name() or '').strip()
    return name or 'نام ثبت نشده'


def _node(profile):
    approved = ReferralSale.objects.filter(
        lead__referrer=profile, status__in=('approved', 'paid')
    )
    sales = approved.aggregate(x=Sum('amount'))['x'] or 0
    return {
        'id': profile.pk,
        'parent_id': profile.sponsor_id,
        'name': _display_name(profile),
        'phone': profile.phone or '',
        'photo': _photo_url(profile),
        'level': profile.level,
        'leads': profile.leads.count(),
        'won': profile.leads.filter(status='won').count(),
        'sales': int(sales),
        'code': profile.referral_code,
        'tree_url': f'/referrals/network/tree/{profile.pk}/',
    }


def _subtree_ids(root, allowed):
    allowed_ids = set(allowed.values_list('id', flat=True))
    ids = [root.pk]
    frontier = [root.pk]
    for _ in range(2):
        children = list(ReferralProfile.objects.filter(
            sponsor_id__in=frontier, is_active=True
        ).exclude(user__profile__role='call_center').values_list('id', flat=True))
        children = [pk for pk in children if pk in allowed_ids]
        ids.extend(children)
        frontier = children
        if not frontier:
            break
    return ids


@login_required
def referral_tree_all(request):
    current = _ensure_profile(request.user)
    profiles = _visible_profiles(request, current)
    nodes = [_node(p) for p in profiles]
    return render(request, 'core/referrals/tree.html', {
        'tree_nodes': nodes,
        'tree_title': 'درخت کل شبکه فروش',
        'tree_subtitle': 'کل ساختار شبکه در یک نما؛ برای جزئیات روی هر فرد بزنید.',
        'focus_profile': None,
        'is_full_tree': True,
    })


@login_required
def referral_tree_person(request, pk):
    current = _ensure_profile(request.user)
    allowed = _visible_profiles(request, current)
    focus = get_object_or_404(allowed, pk=pk)
    ids = _subtree_ids(focus, allowed)
    profiles = allowed.filter(pk__in=ids)
    nodes = [_node(p) for p in profiles]
    return render(request, 'core/referrals/tree.html', {
        'tree_nodes': nodes,
        'tree_title': f'درخت شبکه {_display_name(focus)}',
        'tree_subtitle': 'خود فرد و زیرمجموعه‌های مستقیم و سطح بعدی او.',
        'focus_profile': focus,
        'is_full_tree': False,
    })
