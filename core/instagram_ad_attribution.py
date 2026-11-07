"""Stable, explicit attribution for Instagram story advertising links.

The public /instagram/ads/ link stays generic. Only the staff-made
?ad_page=... links name the external page carrying the advertisement.
No Instagram referrer/header is treated as proof of the publishing page.
"""
import re
from urllib.parse import parse_qs, urlparse

from django.db.models import Q


# Use the same predicates for SQL filters, source labels and deferred routing.
# Query boundaries prevent "paid_story_extra" and nested URLs matching ads.
ADS_PATH_PATTERN = r'^[^?#]*/instagram/ads/([?#]|$)'
PAID_INSTAGRAM_PATTERN = r'^[^?#]*/instagram/[^#]*[?&]utm_medium=(paid|paid_story|paid_social)(&|#|$)'


def advertising_lead_q():
    return (
        Q(notes__icontains='[entry:advertising]')
        | Q(source_url__iregex=ADS_PATH_PATTERN)
        | Q(source_url__iregex=PAID_INSTAGRAM_PATTERN)
    )


def is_paid_instagram_ad(lead):
    notes = str(getattr(lead, 'notes', '') or '').lower()
    source_url = str(getattr(lead, 'source_url', '') or '')
    return bool(
        '[entry:advertising]' in notes
        or re.search(ADS_PATH_PATTERN, source_url, re.I)
        or re.search(PAID_INSTAGRAM_PATTERN, source_url, re.I)
    )


def normalize_ad_page(raw):
    """Return a safe, short page name/handle for storage and display."""
    value = str(raw or '').strip()[:300]
    if not value:
        return ''
    candidate = value
    if re.match(r'^(?:www\.)?instagram\.com/', candidate, re.I):
        candidate = 'https://' + candidate
    if candidate.lower().startswith(('https://', 'http://')):
        try:
            url = urlparse(candidate)
            hostname = (url.hostname or '').lower()
            if hostname in ('instagram.com', 'www.instagram.com', 'm.instagram.com'):
                value = (url.path.strip('/').split('/') or [''])[0]
        except ValueError:
            pass
    value = value.strip().lstrip('@')
    value = re.sub(r'[^\w.\-\s]', '', value, flags=re.UNICODE)
    value = re.sub(r'\s+', ' ', value).strip(' .-')
    return value[:48]


def ad_page_from_lead(lead):
    """Use saved metadata; URL supports the first releases of link builder."""
    notes = str(getattr(lead, 'notes', '') or '')
    marker = re.search(r'\[ad_page:([^\]]{1,120})\]', notes)
    if marker:
        return normalize_ad_page(marker.group(1))
    source_url = str(getattr(lead, 'source_url', '') or '')
    if source_url:
        try:
            raw = (parse_qs(urlparse(source_url).query).get('ad_page') or [''])[0]
            return normalize_ad_page(raw)
        except (ValueError, TypeError):
            return ''
    return ''


def advertising_source_label(lead):
    page = ad_page_from_lead(lead)
    if not page:
        return 'تبلیغات'
    rendered = '@' + page if ' ' not in page else page
    return f'تبلیغات · {rendered}'
