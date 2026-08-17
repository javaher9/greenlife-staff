from django import template
from django.utils import timezone
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
def fa(value): return to_persian_digits(value)

@register.filter
def toman(value):
    try: return to_persian_digits(f'{int(value):,}') + ' تومان'
    except Exception: return '۰ تومان'
