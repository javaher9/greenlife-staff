"""Server-side operations scope; no new organizational or finance privileges."""
from django.contrib.auth.models import User
from django.db.models import Q
from .country_workspace import scoped_queryset

PERSONNEL_ROLES = ('employee', 'call_center', 'consultant', 'doctor', 'receptionist', 'quality_control')


def supervised_users(request):
    profile = getattr(request.user, 'profile', None)
    if not request.user.is_active or not profile or not profile.is_active:
        return User.objects.none()
    qs = scoped_queryset(request, User.objects.filter(is_active=True, profile__is_active=True), 'profile__country')
    if profile.role == 'admin':
        return qs.exclude(pk=request.user.pk)
    qs = qs.filter(profile__role__in=PERSONNEL_ROLES).exclude(pk=request.user.pk)
    if profile.role == 'internal_manager':
        return qs
    if profile.role == 'manager' and profile.branch_id:
        return qs.filter(profile__branch_id=profile.branch_id)
    return qs.none()


def visible_leaves(request):
    from .models import LeaveRequest
    return LeaveRequest.objects.filter(Q(user__in=supervised_users(request)) | Q(user=request.user))


def can_review_leave(request, leave):
    return supervised_users(request).filter(pk=leave.user_id).exists()
