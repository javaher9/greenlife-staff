from django import template

register=template.Library()


@register.filter
def mask_phone(value):
    """Mask patient/customer mobile numbers for non-privileged staff UI."""
    raw=''.join(ch for ch in str(value or '') if ch.isdigit())
    if not raw:
        return '—'
    if len(raw)<=7:
        return '***'
    return f'{raw[:4]}***{raw[-4:]}'
