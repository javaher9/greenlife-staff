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


INSTAGRAM_PAGE_LABELS = {
    'greenlifeclinics': 'Greenlifeclinics',
    'drjavaherian': 'Drjavaherian',
    'greenlife_before_after': 'Greenlife.before.after',
    'greenlife_cafe': 'Greenlife.cafe',
    'greenlife_rejim_ir': 'Greenlife.rejim.ir',
    'greenlife_camp': 'Greenlife.camp',
}


class FlowerLeadProxy:
    """Lead proxy for call-center display wording and normalized lead origins."""
    def __init__(self, lead):
        self._flower_lead = lead

    def __getattr__(self, name):
        return getattr(self._flower_lead, name)

    @property
    def assigned_to(self):
        if not self._flower_lead.assigned_to_id:
            return None
        return FlowerProfileProxy(self._flower_lead.assigned_to)

    def _is_instagram_lead(self):
        lead=self._flower_lead
        notes=str(getattr(lead,'notes','') or '').lower()
        source_url=str(getattr(lead,'source_url','') or '').lower()
        group_name=str(getattr(getattr(lead,'group',None),'name','') or '')
        ref_username=str(getattr(getattr(getattr(lead,'referrer',None),'user',None),'username','') or '').lower()
        return (
            'instagram' in source_url or '/instagram/' in source_url
            or '[instagram_page:' in notes or '[channel:instagram]' in notes
            or 'اینستاگرام' in group_name
            or ref_username in ('instagram-lead-source','lead-source-instagram')
        )

    @property
    def instagram_page_display(self):
        lead=self._flower_lead
        notes=str(getattr(lead,'notes','') or '')
        lowered=notes.lower()

        # New structured marker is the strongest source of truth.
        marker='[instagram_page:'
        if marker in lowered:
            raw=lowered.split(marker,1)[1].split(']',1)[0].strip()
            if raw in INSTAGRAM_PAGE_LABELS:
                return INSTAGRAM_PAGE_LABELS[raw]

        # Older rows store a human-readable "پیج: ..." fragment.
        human_marker='پیج:'
        if human_marker in notes:
            value=notes.split(human_marker,1)[1].split('|',1)[0].strip()
            if value:
                return value[:80]

        # Public Instagram links carry the page slug in ?source=...
        source_url=str(getattr(lead,'source_url','') or '')
        if source_url:
            try:
                from urllib.parse import parse_qs, urlparse
                slug=(parse_qs(urlparse(source_url).query).get('source') or [''])[0].strip().lower()
                if slug in INSTAGRAM_PAGE_LABELS:
                    return INSTAGRAM_PAGE_LABELS[slug]
            except (ValueError,TypeError):
                pass

        # Legacy/API Instagram rows did not persist the page name. Their official
        # Green Life source profile represents the main Greenlifeclinics page.
        if self._is_instagram_lead():
            ref_username=str(getattr(getattr(getattr(lead,'referrer',None),'user',None),'username','') or '').lower()
            if ref_username in ('instagram-lead-source','lead-source-instagram'):
                return 'Greenlifeclinics'
        return ''

    @property
    def instagram_entry_display(self):
        if not self._is_instagram_lead():
            return ''
        return 'لینک' if getattr(self._flower_lead,'source','') in ('link','qr') else 'دستی'

    @property
    def lead_group_display(self):
        lead=self._flower_lead
        group=getattr(lead,'group',None)
        raw=str(getattr(group,'name','') or '')
        if self._is_instagram_lead():
            return f'اینستاگرام - {self.instagram_entry_display}'
        source_url=str(getattr(lead,'source_url','') or '').lower()
        if '/beytoote/' in source_url or 'beytoote' in source_url or 'bitoteh' in source_url:
            return 'بنر - سلامت'
        return raw or '—'

    @property
    def source_origin_display(self):
        page=self.instagram_page_display
        if self._is_instagram_lead():
            parts=['اینستاگرام',self.instagram_entry_display]
            if page:
                parts.append(page)
            return ' · '.join(part for part in parts if part)
        try:
            return self._flower_lead.get_source_display()
        except Exception:
            return str(getattr(self._flower_lead,'source','') or '')

    @property
    def source_page_display(self):
        """Canonical page/source label used by the Lead Hub table."""
        if self._is_instagram_lead():
            return self.instagram_page_display or 'Greenlifeclinics'
        source_url=str(getattr(self._flower_lead,'source_url','') or '').lower()
        if '/beytoote/' in source_url or 'beytoote' in source_url or 'bitoteh' in source_url:
            return 'بیتوته'
        if '/aparat/' in source_url or 'aparat' in source_url:
            return 'آپارات'
        if 'greenlifeclinics.com' in source_url:
            return 'Greenlifeclinics'
        try:
            label=self._flower_lead.get_source_display()
        except Exception:
            label=''
        return label or '—'

    @property
    def notes(self):
        notes = str(getattr(self._flower_lead, 'notes', '') or '')
        if '[instagram_page:' in notes:
            before, rest = notes.split('[instagram_page:', 1)
            rest = rest.split(']', 1)[1] if ']' in rest else ''
            notes = (before.rstrip(' |') + (' | ' + rest.lstrip(' |') if rest.strip(' |') else '')).strip()
        return notes

    def get_status_display(self):
        return call_center_lead_stage(self._flower_lead)
