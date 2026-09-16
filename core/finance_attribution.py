"""Keep call-center sales attribution in sync with real approved appointment income."""
from decimal import Decimal

from django.db.models import Sum
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import FinancialTransaction, ReferralSale


def sync_call_center_sale(transaction):
    """Mirror approved appointment income into the lead sale used by call-center KPIs.

    Only income tied to a real appointment/lead and a call-center owner qualifies.
    Amount is recomputed from approved transactions so retries cannot double count.
    """
    appointment=transaction.appointment
    if not appointment or not appointment.lead_id:
        return
    owner_id=transaction.call_center_owner_id or appointment.lead.first_appointment_by_id
    if not owner_id:
        return
    lead=appointment.lead
    total=(
        FinancialTransaction.objects.filter(
            appointment__lead_id=lead.pk,
            entry_type='inc',
            review_status='approved',
        )
        .filter(
            # Preserve the immutable first-booking ownership rule.
            appointment__lead__first_appointment_by_id=owner_id,
        )
        .aggregate(total=Sum('amount'))['total'] or Decimal('0')
    )
    if total <= 0:
        return
    sale,_=ReferralSale.objects.get_or_create(
        lead=lead,
        defaults={
            'sale_date':transaction.occurred_at.date(),
            'amount':total,
            'status':'approved',
            'recorded_by_id':owner_id,
            'note':'ثبت خودکار از پرداخت تأییدشده نوبت',
        },
    )
    changed=[]
    if sale.amount != total:
        sale.amount=total; changed.append('amount')
    latest_date=transaction.occurred_at.date()
    if sale.sale_date != latest_date:
        sale.sale_date=latest_date; changed.append('sale_date')
    if sale.status=='draft':
        sale.status='approved'; changed.append('status')
    if changed:
        changed.append('updated_at')
        sale.save(update_fields=changed)
    if lead.status not in ('won','lost'):
        lead.status='won'
        lead.save(update_fields=['status','updated_at'])


@receiver(post_save, sender=FinancialTransaction, dispatch_uid='sync_call_center_sale_from_finance')
def financial_transaction_saved(sender, instance, **kwargs):
    if instance.entry_type=='inc' and instance.review_status=='approved' and instance.appointment_id:
        sync_call_center_sale(instance)
