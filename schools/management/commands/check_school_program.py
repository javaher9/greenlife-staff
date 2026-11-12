from django.core.management.base import BaseCommand
from core.models import EmployeeProfile
from schools.models import SchoolProgram

class Command(BaseCommand):
    help = 'Read-only deployment readiness for the schools module; no personal data.'
    def handle(self, *args, **options):
        enabled = EmployeeProfile.objects.filter(is_active=True, user__is_active=True, can_manage_schools=True).count()
        self.stdout.write(f'schools_module=ready coordinators_enabled={enabled} programs={SchoolProgram.objects.count()}')
        if not enabled:
            self.stdout.write('Coordinator account needs exact identity verification; no ambiguous account was granted access.')
