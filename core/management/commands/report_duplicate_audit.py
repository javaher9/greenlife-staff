from django.core.management.base import BaseCommand
from django.db.models import Count
from core.models import DailyReport

class Command(BaseCommand):
    help = 'List likely duplicate reports by user/audio file name.'

    def handle(self,*args,**kwargs):
        groups=(DailyReport.objects.exclude(audio='')
                .values('user_id','audio')
                .annotate(n=Count('id'))
                .filter(n__gt=1)
                .order_by('-n'))
        if not groups:
            self.stdout.write(self.style.SUCCESS('No exact duplicate audio references found.'))
            return
        for g in groups:
            self.stdout.write(f"user={g['user_id']} audio={g['audio']} count={g['n']}")
