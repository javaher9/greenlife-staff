from django import template
from django.utils import timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from core.jalali import format_jalali, to_persian_digits
register = template.Library()
@register.filter
def jdate(value): return format_jalali(value)
@register.filter
def jdatetime(value):
    if value:
        try: value = timezone.localtime(value)
        except Exception: pass
    return format_jalali(value, with_time=True)

@register.filter
def jdate_en(value):
    """Render a Jalali date with Latin digits."""
    return format_jalali(value, persian_digits=False)

@register.filter
def jdatetime_en(value):
    """Render a localized Jalali date/time with Latin digits."""
    if value:
        try: value = timezone.localtime(value)
        except Exception: pass
    return format_jalali(value, with_time=True, persian_digits=False)
@register.filter
def fa(value): return to_persian_digits(value)

@register.filter
def toman(value):
    try: return to_persian_digits(f'{int(value):,}') + ' تومان'
    except Exception: return '۰ تومان'

@register.filter
def en_number(value):
    """Render a numeric value with Latin digits and no unnecessary decimals."""
    try:
        number=Decimal(str(value))
    except (InvalidOperation,TypeError,ValueError):
        return '0'
    rendered=f'{number:f}'
    if '.' in rendered:
        rendered=rendered.rstrip('0').rstrip('.')
    return rendered or '0'

@register.filter
def million_toman(value):
    """Display a stored rial amount as compact million tomans using Latin digits."""
    try:
        millions=Decimal(str(value))/Decimal('10000000')
    except (InvalidOperation,TypeError,ValueError):
        return '0'
    rendered=f'{millions.quantize(Decimal("0.001"),rounding=ROUND_HALF_UP):f}'.rstrip('0').rstrip('.')
    return rendered or '0'
