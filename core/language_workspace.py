from django.conf import settings

from .staff_i18n import (
    SUPPORTED_UI_LANGUAGES,
    SUPPORTED_UI_LANGUAGE_CODES,
    UI_LANGUAGE_SESSION_KEY,
    normalize_ui_language,
    ui_direction,
)


def _profile_for(user):
    if not user or not getattr(user, 'is_authenticated', False):
        return None
    return getattr(user, 'profile', None)


def resolve_staff_language(request):
    """Resolve UI language independently from country/workspace.

    Priority:
    1) explicit session choice
    2) authenticated staff preference
    3) Persian safe default
    """
    session_value = request.session.get(UI_LANGUAGE_SESSION_KEY)
    profile = _profile_for(getattr(request, 'user', None))
    profile_value = getattr(profile, 'preferred_language', '') if profile else ''

    if session_value in SUPPORTED_UI_LANGUAGE_CODES:
        language = session_value
    elif profile_value in SUPPORTED_UI_LANGUAGE_CODES:
        language = profile_value
        request.session[UI_LANGUAGE_SESSION_KEY] = language
    else:
        language = 'fa'
        request.session[UI_LANGUAGE_SESSION_KEY] = language

    # If a staff member explicitly selected a language on the login page,
    # carry it into their persistent profile after authentication.
    if profile and profile.preferred_language != language:
        profile.preferred_language = language
        profile.save(update_fields=['preferred_language'])

    return {
        'language': language,
        'direction': ui_direction(language),
        'languages': SUPPORTED_UI_LANGUAGES,
    }


class StaffLanguageMiddleware:
    """Attach the active UI language to every request after AuthenticationMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        state = resolve_staff_language(request)
        request.ui_language = state['language']
        request.ui_direction = state['direction']
        request.ui_languages = state['languages']
        return self.get_response(request)
