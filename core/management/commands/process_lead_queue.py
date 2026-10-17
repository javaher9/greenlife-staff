import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from core.lead_routing import release_pending_leads_if_ready

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Distribute pending call-center leads independently of SMS/network latency.'

    def add_arguments(self, parser):
        parser.add_argument('--loop', action='store_true')
        parser.add_argument('--interval', type=int, default=15)

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            try:
                count = release_pending_leads_if_ready()
                if count:
                    self.stdout.write(f'Pending leads assigned: {count}')
            except Exception:
                if not options['loop']:
                    raise
                logger.exception('Lead routing failed; retry on next tick')
            finally:
                close_old_connections()
            if not options['loop']:
                return
            time.sleep(max(5, min(options['interval'], 60)))
