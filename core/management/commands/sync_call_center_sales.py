from django.core.management.base import BaseCommand
from core.finance_attribution import sync_call_center_sale
from core.models import FinancialTransaction


class Command(BaseCommand):
    help='Backfill/repair call-center sales attribution from approved appointment income.'

    def handle(self,*args,**options):
        qs=(FinancialTransaction.objects.filter(
            entry_type='inc',review_status='approved',appointment__lead__isnull=False,
        ).select_related('appointment__lead'))
        count=0
        for tx in qs.iterator():
            before=getattr(tx.appointment.lead,'sale',None)
            sync_call_center_sale(tx)
            count+=1
        self.stdout.write(self.style.SUCCESS(f'Checked {count} approved appointment payments.'))
