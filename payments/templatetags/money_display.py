from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()

@register.filter
def million_toman(value):
    """Amount in tomans as compact millions, without trailing zeros."""
    try:
        amount = Decimal(str(value or 0)) / Decimal('1000000')
    except (InvalidOperation, TypeError, ValueError):
        return '—'
    result = format(amount.quantize(Decimal('0.001')), ',f')
    return result.rstrip('0').rstrip('.') if '.' in result else result
