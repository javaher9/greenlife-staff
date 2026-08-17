from django.core.management.base import BaseCommand
from core.finance import sync_crm
class Command(BaseCommand):
    help='Sync financial/revenue transactions from CRM API'
    def add_arguments(self,p): p.add_argument('--start'); p.add_argument('--end')
    def handle(self,*args,**o): self.stdout.write(self.style.SUCCESS(str(sync_crm(o.get('start'),o.get('end')))))
