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
