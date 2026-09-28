import time

from django.core.management.base import BaseCommand

from core.sms_automation import process_due_sms


class Command(BaseCommand):
    help='Dispatch due SMS queue entries. Use --loop for the dedicated worker.'

    def add_arguments(self,parser):
        parser.add_argument('--loop',action='store_true')
        parser.add_argument('--interval',type=int,default=30)
        parser.add_argument('--batch-size',type=int,default=25)

    def handle(self,*args,**options):
        while True:
            count=process_due_sms(batch_size=max(1,min(options['batch_size'],100)))
            if count:
                self.stdout.write(f'SMS queue processed: {count}')
            if not options['loop']:
                return
            time.sleep(max(5,min(options['interval'],3600)))
