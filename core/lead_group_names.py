"""Stable grouping for call-center folders with spelling variants."""
import re
import unicodedata


DOCTOR_DESK_NAME = 'میزهای قدیمی دکتر جواهریان'


def normalized_group_name(value):
    value = unicodedata.normalize('NFKC', value or '').translate(str.maketrans({'ي': 'ی', 'ك': 'ک'}))
    value = re.sub(r'[\u064b-\u065f\u0670\u0640]', '', value)
    value = re.sub(r'[\u200c\u200d\s]+', ' ', value).strip(' \u00ab\u00bb-–—_').casefold()
    if 'قدیمی' in value and 'دکتر' in value and re.match(r'^(?:مزو|میز)', value):
        return DOCTOR_DESK_NAME
    return value


def preferred_group_name(value):
    key = normalized_group_name(value)
    if key == DOCTOR_DESK_NAME:
        return DOCTOR_DESK_NAME
    if key == 'vip':
        return 'VIP'
    return value
