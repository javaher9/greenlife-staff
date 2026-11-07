from django.conf import settings


def can_approve(user):
    return bool(user and user.is_authenticated and user.is_active and (
        user.is_superuser or (user.username or '').lower() in settings.EXECUTIVE_USERNAMES
    ))


def can_manage(user):
    if can_approve(user):
        return True
    profile = getattr(user, 'profile', None)
    return bool(user and user.is_authenticated and user.is_active and profile
                and profile.is_active and profile.role in {'admin','internal_manager'})
