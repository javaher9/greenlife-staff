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
    (('زهرا آزادی', 'آزادی', 'ازادی', 'azadi'), 'یاسمن'),
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


def call_center_lead_stage(lead):
    """Operational wording for a lead inside call-center/Lead Hub screens.

    The database status values stay unchanged. A contacted lead with a future
    follow-up date is shown as needing another follow-up; an appointment and a
    lost lead get the business wording used by the call-center team.
    """
    if lead is None:
        return ''
    status = getattr(lead, 'status', '') or ''
    if status == 'contacted' and getattr(lead, 'next_follow_up', None):
        return 'نیاز به پیگیری مجدد'
    labels = {
        'new': 'جدید',
        'contacted': 'تماس گرفته شد',
        'appointment': 'نوبت داده شد',
        'visited': 'مراجعه کرد',
        'won': 'فروش موفق',
        'lost': 'تمایل به پیگیری ندارد',
    }
    if status in labels:
        return labels[status]
    try:
        return lead.get_status_display()
    except Exception:
        return status


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
    """Lead proxy for call-center display wording and flower-name ownership."""
    def __init__(self, lead):
        self._flower_lead = lead

    def __getattr__(self, name):
        return getattr(self._flower_lead, name)

    @property
    def assigned_to(self):
        if not self._flower_lead.assigned_to_id:
            return None
        return FlowerProfileProxy(self._flower_lead.assigned_to)

    @property
    def instagram_page_display(self):
        notes = str(getattr(self._flower_lead, 'notes', '') or '')
        marker = 'پیج:'
        if marker not in notes:
            return ''
        value = notes.split(marker, 1)[1].split('|', 1)[0].strip()
        return value[:80]

    def get_status_display(self):
        return call_center_lead_stage(self._flower_lead)
