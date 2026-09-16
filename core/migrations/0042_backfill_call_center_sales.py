from django.db import migrations
from django.db.models import Sum


def backfill(apps, schema_editor):
    FinancialTransaction=apps.get_model('core','FinancialTransaction')
    ReferralSale=apps.get_model('core','ReferralSale')
    ReferralLead=apps.get_model('core','ReferralLead')

    lead_ids=(FinancialTransaction.objects.filter(
        entry_type='inc',review_status='approved',appointment__lead__isnull=False,
        appointment__lead__first_appointment_by__isnull=False,
    ).values_list('appointment__lead_id',flat=True).distinct())

    for lead_id in lead_ids.iterator():
        txs=FinancialTransaction.objects.filter(
            entry_type='inc',review_status='approved',appointment__lead_id=lead_id,
            appointment__lead__first_appointment_by__isnull=False,
        )
        total=txs.aggregate(total=Sum('amount'))['total'] or 0
        latest=txs.order_by('-occurred_at').first()
        if not latest or total<=0:
            continue
        owner_id=latest.appointment.lead.first_appointment_by_id
        sale,_=ReferralSale.objects.get_or_create(
            lead_id=lead_id,
            defaults={
                'sale_date':latest.occurred_at.date(),'amount':total,'status':'approved',
                'recorded_by_id':owner_id,'note':'ثبت خودکار از پرداخت تأییدشده نوبت',
            },
        )
        changed=[]
        if sale.amount != total:
            sale.amount=total; changed.append('amount')
        if sale.status=='draft':
            sale.status='approved'; changed.append('status')
        if changed:
            sale.save(update_fields=changed)
        ReferralLead.objects.filter(pk=lead_id).exclude(status__in=('won','lost')).update(status='won')


class Migration(migrations.Migration):
    dependencies=[('core','0041_restore_kamelia_call_center')]
    operations=[migrations.RunPython(backfill,migrations.RunPython.noop)]
