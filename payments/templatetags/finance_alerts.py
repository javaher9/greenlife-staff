from django import template
from payments.models import PaymentRequest

register=template.Library()

@register.simple_tag
def open_payment_count(user):
    if not user or not user.is_authenticated or not user.is_active:
        return 0
    profile=getattr(user,'profile',None)
    if not profile or not profile.is_active or not profile.can_execute_payments:
        return 0
    return PaymentRequest.objects.filter(assigned_to=user,state='approved').count()
