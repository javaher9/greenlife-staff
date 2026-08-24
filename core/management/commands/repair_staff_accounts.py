from django.contrib.auth.hashers import identify_hasher
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import EmployeeProfile


class Command(BaseCommand):
    help = 'Audit and safely repair staff accounts recreated without profiles or password hashing.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Create missing profiles and hash passwords that were accidentally stored as plain text.',
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
