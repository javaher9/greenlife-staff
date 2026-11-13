from django.conf import settings
from .models import SchoolProgram


def is_executive(user):
    if not user or not user.is_authenticated or not user.is_active:
        return False
    profile = getattr(user, 'profile', None)
    return bool(user.is_superuser or user.username.lower() in settings.EXECUTIVE_USERNAMES or (profile and profile.is_active and profile.role == 'admin'))


def can_manage(user):
    if is_executive(user):
        return True
    profile = getattr(user, 'profile', None)
    return bool(user and user.is_authenticated and user.is_active and profile and profile.is_active and profile.branch_id and profile.branch.is_active and profile.can_manage_schools)


def can_clinical(user):
    if is_executive(user):
        return True
    p = getattr(user, 'profile', None)
    return bool(user and user.is_authenticated and user.is_active and p and p.is_active and p.role == 'doctor' and p.branch_id and p.branch.is_active)


def programs_for(user, clinical=False):
    qs = SchoolProgram.objects.select_related('organization__branch', 'coordinator')
    if is_executive(user):
        return qs
    if (can_clinical(user) if clinical else can_manage(user)):
        return qs.filter(organization__branch_id=user.profile.branch_id)
    return qs.none()


def school_access(request):
    return {'schools_access': can_manage(getattr(request, 'user', None)), 'schools_clinical_access': can_clinical(getattr(request, 'user', None))}
