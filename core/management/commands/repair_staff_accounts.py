import logging
from collections import Counter

from django.conf import settings
from django.contrib.auth import BACKEND_SESSION_KEY, HASH_SESSION_KEY, SESSION_KEY
from django.contrib.auth.hashers import identify_hasher
from django.contrib.auth.models import User
from django.core.management import CommandError
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test import Client

from core.models import EmployeeProfile


class Command(BaseCommand):
    help = 'Audit and safely repair staff accounts recreated without profiles or password hashing.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Create missing profiles and hash passwords that were accidentally stored as plain text.',
        )
        parser.add_argument(
            '--verify-sessions',
            action='store_true',
            help='Render the first authenticated page for every active account and report aggregate failures.',
        )

    @staticmethod
    def _password_state(user):
        if not user.has_usable_password():
            return 'unusable'
        try:
            identify_hasher(user.password)
        except ValueError:
            return 'raw'
        return 'encoded'

    @transaction.atomic
    def handle(self, *args, **options):
        apply_repairs = options['apply']
        counts = {
            'users': 0,
            'missing_profiles': 0,
            'raw_passwords': 0,
            'unusable_passwords': 0,
            'profiles_created': 0,
            'passwords_hashed': 0,
        }

        for user in User.objects.select_for_update().order_by('pk'):
            counts['users'] += 1
            if not EmployeeProfile.objects.filter(user=user).exists():
                counts['missing_profiles'] += 1
                if apply_repairs:
                    EmployeeProfile.objects.create(
                        user=user,
                        role='admin' if user.is_superuser else 'employee',
                        is_active=user.is_active,
                    )
                    counts['profiles_created'] += 1

            password_state = self._password_state(user)
            if password_state == 'raw':
                counts['raw_passwords'] += 1
                if apply_repairs:
                    # Preserve the password the operator entered, but store it
                    # with Django's configured one-way password hasher.
                    raw_password = user.password
                    user.set_password(raw_password)
                    user.save(update_fields=['password'])
                    counts['passwords_hashed'] += 1
            elif password_state == 'unusable':
                counts['unusable_passwords'] += 1

        mode = 'repair' if apply_repairs else 'audit'
        self.stdout.write(
            'Staff account integrity '
            f'({mode}): users={counts["users"]}, '
            f'missing_profiles={counts["missing_profiles"]}, '
            f'profiles_created={counts["profiles_created"]}, '
            f'raw_passwords={counts["raw_passwords"]}, '
            f'passwords_hashed={counts["passwords_hashed"]}, '
            f'unusable_passwords={counts["unusable_passwords"]}'
        )
        if counts['unusable_passwords']:
            self.stdout.write(self.style.WARNING(
                'Some accounts have intentionally unusable passwords; they were not reset automatically.'
            ))

        if options['verify_sessions']:
            self._verify_sessions()

    def _verify_sessions(self):
        checked = 0
        app_admin_checked = 0
        django_admin_checked = 0
        role_admin_without_staff = 0
        errors = Counter()
        host = (settings.ALLOWED_HOSTS or ['localhost'])[0]
        if host == '*':
            host = 'localhost'

        # Do not put Django tracebacks (which may contain staff data) in the
        # public Actions log. Only aggregate exception classes are reported.
        previous_disable = logging.root.manager.disable
        logging.disable(logging.CRITICAL)
        try:
            for user in User.objects.filter(is_active=True).order_by('pk'):
                client = Client(raise_request_exception=True)
                session = client.session
                session[SESSION_KEY] = str(user.pk)
                session[BACKEND_SESSION_KEY] = 'django.contrib.auth.backends.ModelBackend'
                session[HASH_SESSION_KEY] = user.get_session_auth_hash()
                session.save()
                try:
                    response = client.get('/', follow=True, secure=True, HTTP_HOST=host)
                    if response.status_code >= 500:
                        errors[f'HTTP_{response.status_code}'] += 1

                    profile_role = getattr(getattr(user, 'profile', None), 'role', '')
                    if profile_role in ('admin', 'internal_manager', 'manager'):
                        app_admin_checked += 1
                        response = client.get('/live/', follow=True, secure=True, HTTP_HOST=host)
                        if response.status_code >= 500:
                            errors[f'APP_ADMIN_HTTP_{response.status_code}'] += 1

                    if profile_role == 'admin' and not user.is_staff:
                        role_admin_without_staff += 1

                    if user.is_staff:
                        django_admin_checked += 1
                        response = client.get('/admin/', follow=True, secure=True, HTTP_HOST=host)
                        if response.status_code >= 500:
                            errors[f'DJANGO_ADMIN_HTTP_{response.status_code}'] += 1
                except Exception as exc:
                    errors[type(exc).__name__] += 1
                finally:
                    client.session.flush()
                checked += 1
        finally:
            logging.disable(previous_disable)

        summary = ','.join(f'{name}:{count}' for name, count in sorted(errors.items())) or 'none'
        self.stdout.write(f'Staff session verification: checked={checked}, errors={summary}')
        self.stdout.write(
            'Admin session verification: '
            f'app_admin_checked={app_admin_checked}, '
            f'django_admin_checked={django_admin_checked}, '
            f'role_admin_without_staff={role_admin_without_staff}'
        )
        if errors:
            raise CommandError('Authenticated staff session verification failed.')
