from django.core.management.base import BaseCommand
from core.operations_monitor import reconcile_direct_gap

class Command(BaseCommand):
    help = 'Persist manual Instagram DM gaps using Tehran time; no external messages.'
    def handle(self, *args, **options):
        reconcile_direct_gap(scheduled=True)
        self.stdout.write('Manual DM monitor completed.')
