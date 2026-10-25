from django import template
from payments.models import PaymentRequest

register = template.Library()

@register.simple_tag
def assigned_payment_count(user):
    if not getattr(user, 'is_authenticated', False) or not user.is_active:
        return 0
    return PaymentRequest.objects.filter(assigned_to=user, state='approved').count()
