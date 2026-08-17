from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from core.operations import apply_missing_report_penalties

class Command(BaseCommand):
    help='اعمال جریمه گزارش روزانه ارسال‌نشده برای شب قبل'
    def add_arguments(self, parser): parser.add_argument('--today',action='store_true',help='برای تست روی امروز اجرا شود')
    def handle(self,*args,**options):
        day=timezone.localdate() if options['today'] else timezone.localdate()-timedelta(days=1)
        count=apply_missing_report_penalties(day)
        self.stdout.write(self.style.SUCCESS(f'{count} جریمه برای {day} ثبت شد.'))
