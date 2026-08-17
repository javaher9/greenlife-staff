from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import Branch,EmployeeProfile
class Command(BaseCommand):
    def handle(self,*args,**kwargs):
        branches={n:Branch.objects.get_or_create(name=n)[0] for n in ['افسریه','نیاوران','پونک','اصفهان','ارومیه']}
        if not User.objects.filter(username='admin').exists():
            u=User.objects.create_superuser('admin','admin@example.com','ChangeMeNow!')
            EmployeeProfile.objects.create(user=u,role='admin',job_title='مدیر سیستم')
            self.stdout.write(self.style.WARNING('کاربر اولیه admin با رمز ChangeMeNow! ساخته شد؛ فوراً رمز را تغییر دهید.'))
