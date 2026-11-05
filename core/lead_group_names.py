"""Stable grouping for call-center folders with spelling variants."""
import re
import unicodedata


DOCTOR_DESK_NAME = 'مزوهای قدیمی دکتر'

CANONICAL_GROUPS = (
    'وب سایت', 'مزوهای قدیمی دکتر', 'اینستاگرام', 'VIP',
    'ترکیه', 'شبکه فروش پرسنل', 'کمپ',
)


def normalized_group_name(value):
    value = unicodedata.normalize('NFKC', value or '').translate(str.maketrans({'ي': 'ی', 'ك': 'ک'}))
    value = re.sub(r'[\u064b-\u065f\u0670\u0640]', '', value)
    value = re.sub(r'[\u200c\u200d\s]+', ' ', value).strip(' \u00ab\u00bb-–—_').casefold()
    if 'دکتر' in value and re.match(r'^(?:مزو|میز)', value) and (
        'قدیمی' in value or value in ('میزهای آقای دکتر', 'میزهای دکتر جواهریان')
    ):
        return DOCTOR_DESK_NAME
    compact = re.sub(r'[\s\-–—_]+', '', value)
    if compact in ('وبسایت', 'ورودیوبسایت', 'website', 'ورودیwebsite'):
        return 'وب سایت'
    if value in ('اینستاگرام', 'اینستاگرام جدید', 'اینستاگرام - لینک',
                 'اینستاگرام - دستی', 'ورودی اینستاگرام'):
        return 'اینستاگرام'
    if compact in ('ترکیه', 'turkey', 'türkiye|turkey', 'türkiye'):
        return 'ترکیه'
    if value in ('کمپ', 'ورودی کمپین'):
        return 'کمپ'
    return value


def preferred_group_name(value):
    key = normalized_group_name(value)
    for name in CANONICAL_GROUPS:
        if key == normalized_group_name(name):
            return name
    return value


def operational_group_name(value):
    """Keep every new automatic source within the seven approved folders."""
    name = preferred_group_name(value)
    if name in CANONICAL_GROUPS:
        return name
    key = normalized_group_name(value)
    if 'vip' in key:
        return 'VIP'
    if 'ترکیه' in key or 'turkey' in key or 'türkiye' in key:
        return 'ترکیه'
    if 'اینستا' in key:
        return 'اینستاگرام'
    if 'کمپ' in key or 'campaign' in key:
        return 'کمپ'
    if any(part in key for part in ('شبکه', 'شرکت', 'همکار', 'پرسنل', 'معرف', 'پیگیری', 'میز', 'مزو')):
        return 'شبکه فروش پرسنل'
    return 'وب سایت'
