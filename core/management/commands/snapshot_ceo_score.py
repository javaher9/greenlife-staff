from django.core.management.base import BaseCommand
from django.utils import timezone
from core.models import Branch, CEOScoreSnapshot
from core.executive_engine import ceo_score

class Command(BaseCommand):
    help='Store daily CEO Score snapshots for all-company and each active branch.'

    def handle(self,*args,**kwargs):
        day=timezone.localdate()
        scopes=[None]+list(Branch.objects.filter(is_active=True))
        count=0
        for branch in scopes:
            data=ceo_score(branch,day)
            CEOScoreSnapshot.objects.update_or_create(
                date=day,branch=branch,
                defaults={
                    'score':data['score'],'people':data['people'],'operations':data['operations'],
                    'revenue':data['revenue'],'discipline':data['discipline'],
                    'details':{'reasons':data['reasons'],'revenue_current_7d':data['revenue_current_7d'],'revenue_previous_7d':data['revenue_previous_7d']},
                }
            )
            count+=1
        self.stdout.write(self.style.SUCCESS(f'{count} CEO Score snapshots stored for {day}'))
