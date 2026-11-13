from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.test import RequestFactory
from django.urls import resolve
from core.models import EmployeeProfile
from schools.models import SchoolProgram
from schools.permissions import can_manage


def normalized(value):
    return ''.join((value or '').replace('ي', 'ی').replace('ك', 'ک').replace('\u200c', '').split()).lower()

class Command(BaseCommand):
    help = 'Read-only deployment readiness for the schools module; no personal data.'

    def add_arguments(self, parser):
        parser.add_argument('--require-niavaran', action='store_true')

    def handle(self, *args, **options):
        enabled = EmployeeProfile.objects.filter(is_active=True, user__is_active=True, can_manage_schools=True).count()
        self.stdout.write(f'schools_module=ready coordinators_enabled={enabled} programs={SchoolProgram.objects.count()}')
        matches = [p for p in EmployeeProfile.objects.filter(is_active=True, user__is_active=True, role='consultant', branch__is_active=True).select_related('user', 'branch')
                   if normalized(p.branch.name) in ('نیاوران', 'تهراننیاوران', 'niavaran') and
                   (normalized(p.user.last_name) == 'مرادی' or normalized(p.user.username) == 'moradi')]
        ready = len(matches) == 1 and can_manage(matches[0].user)
        self.stdout.write(f'niavaran_moradi_matches={len(matches)} authorized={int(ready)}')
        if options['require_niavaran'] and not ready:
            raise CommandError('Exact Niavaran coordinator is not uniquely authorized; no access was changed.')
        users = [('coordinator', matches[0].user)] if ready else []
        executive = User.objects.filter(is_active=True, username__in=settings.EXECUTIVE_USERNAMES).first() or User.objects.filter(is_active=True, is_superuser=True).first()
        if executive:
            users.append(('executive', executive))
        for role, user in users:
            for path in ('/schools/', '/schools/families/', '/schools/new/'):
                request = RequestFactory().get(path, HTTP_HOST='app.greenlifeclinics.com')
                request.user = user
                request.session = {}
                request.resolver_match = resolve(path)
                response = request.resolver_match.func(request, **request.resolver_match.kwargs)
                if response.status_code != 200:
                    raise CommandError(f'{role} {path} status={response.status_code}')
                self.stdout.write(f'{role} {path} rendered=200')
