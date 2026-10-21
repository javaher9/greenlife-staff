from django import template
from payments.models import PaymentRequest
register=template.Library()

@register.inclusion_tag('payments/embedded_queue.html',takes_context=True)
def approved_payment_queue(context):
    user=context['request'].user
    if not user.is_authenticated:
        return {'items':[]}
    return {'items':PaymentRequest.objects.filter(state='approved',assigned_to=user).order_by('created_at')[:30]}
