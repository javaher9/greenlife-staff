from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.camp_seed import seed_camp_demo

class Command(BaseCommand):
    help='Load local mock/demo data for the GreenLife Camp module.'

    def handle(self,*args,**kwargs):
        owner=User.objects.filter(is_superuser=True).first() or User.objects.filter(profile__role='admin').first() or User.objects.first()
        site=seed_camp_demo(owner)
        self.stdout.write(self.style.SUCCESS(f'Camp demo data loaded: {site}'))
