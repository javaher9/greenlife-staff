from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.db import transaction
from core.models import Branch, EmployeeProfile

STATIONS = [('Scan-niavaran', ('نیاوران','niavaran')),('Scan-poonak',('پونک','poonak')),('Scan-esfehan',('اصفهان','esfehan','isfahan'))]

class Command(BaseCommand):
    help = 'Create disabled, non-personnel scan stations for administrator activation.'
    @transaction.atomic
    def handle(self,*args,**options):
        for username,aliases in STATIONS:
            branch=next((b for b in Branch.objects.all() if any(a.lower() in b.name.lower() for a in aliases)),None)
            if branch is None:
                self.stdout.write(self.style.WARNING(f'{username}: branch not found; skipped'))
                continue
            user,created=User.objects.get_or_create(username=username,defaults={'is_active':False,'is_staff':False})
            if created:
                user.set_unusable_password()
                user.save(update_fields=['password'])
            profile,created_profile=EmployeeProfile.objects.get_or_create(user=user,defaults={'role':'scan_station','branch':branch,'is_active':True,'can_use_sales_network':False})
            if not created_profile and profile.role != 'scan_station':
                self.stdout.write(self.style.WARNING(f'{username}: existing non-station user; skipped'))
                continue
            profile.role='scan_station'
            profile.branch=branch
            profile.can_use_sales_network=False
            profile.save(update_fields=['role','branch','can_use_sales_network'])
            self.stdout.write(f'{username}: configured as scan station for {branch.name}; activate and set password in admin')
