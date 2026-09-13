def _normalize(value):
    return ' '.join(str(value or '').strip().lower().replace('ي', 'ی').replace('ك', 'ک').split())


# Display aliases used only in call-center/lead contexts. Real staff names stay
# untouched for personnel, credentials, attendance and administrative records.
FLOWER_NAME_RULES = (
    (('محمد صالحی', 'صالحی', 'salehi'), 'خورشیدی'),
    (('فاطمه بابایی', 'بابایی', 'babaei', 'babayi', 'babaee'), 'نرگس'),
    (('حدیث توانا', 'توانا', 'tavana'), 'بنفشه'),
    (('پریسا کلکلی', 'کلکلی', 'kolkoli', 'kalakali'), 'کاملیا'),
    (('شیما عباسی', 'عباسی', 'abbasi'), 'لاله'),
)


def call_center_display_name(value):
    """Return the flower alias for a call-center user/profile, with safe fallback."""
    if value is None:
        return ''

    user = getattr(value, 'user', value)
    first_name = getattr(user, 'first_name', '') or ''
    last_name = getattr(user, 'last_name', '') or ''
    username = getattr(user, 'username', '') or ''
    full_name = ' '.join(part for part in (first_name, last_name) if part).strip()
    identity = _normalize(' '.join(part for part in (full_name, username) if part))

    for aliases, flower_name in FLOWER_NAME_RULES:
        if any(_normalize(alias) in identity for alias in aliases):
            return flower_name

    return full_name or username or str(value)


class FlowerUserProxy:
    """User proxy that changes only the call-center display name."""
    def __init__(self, user):
        self._flower_user = user

    def __getattr__(self, name):
        return getattr(self._flower_user, name)

    @property
    def first_name(self):
        return call_center_display_name(self._flower_user)

    @property
    def last_name(self):
        return ''

    def get_full_name(self):
        return call_center_display_name(self._flower_user)

    def __str__(self):
        return call_center_display_name(self._flower_user)


class FlowerProfileProxy:
    """EmployeeProfile proxy for lead/call-center templates."""
    def __init__(self, profile):
        self._flower_profile = profile

    def __getattr__(self, name):
        return getattr(self._flower_profile, name)

    @property
    def user(self):
        return FlowerUserProxy(self._flower_profile.user)

    def __str__(self):
        return call_center_display_name(self._flower_profile)


class FlowerLeadProxy:
    """Lead proxy that exposes the assignee through the flower-name profile proxy."""
    def __init__(self, lead):
        self._flower_lead = lead

    def __getattr__(self, name):
        return getattr(self._flower_lead, name)

    @property
    def assigned_to(self):
        if not self._flower_lead.assigned_to_id:
            return None
        return FlowerProfileProxy(self._flower_lead.assigned_to)
