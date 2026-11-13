from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from schools.models import FamilyEnrollment, SchoolProgram
from schools.services import ensure_school_lead, gandom_operator


class Command(BaseCommand):
    help = 'Idempotently connect existing school registrations to the unique active Gandom operator.'

    def handle(self, *args, **options):
        if not gandom_operator():
            raise CommandError('A unique active Gandom operator is required; no unrelated lead was changed.')
        total = 0
        for pk, program_id in FamilyEnrollment.objects.exclude(status='cancelled').values_list('pk', 'program_id').iterator():
            with transaction.atomic():
                program = SchoolProgram.objects.select_for_update().get(pk=program_id)
                enrollment = FamilyEnrollment.objects.select_for_update().get(pk=pk)
                if enrollment.status == 'pending' and program.is_open:
                    occupied = program.enrollments.filter(status__in=FamilyEnrollment.OCCUPIED).count()
                    enrollment.status = 'ready' if occupied < program.capacity else 'waiting'
                    enrollment.save(update_fields=['status'])
                ensure_school_lead(enrollment)
                total += 1
        self.stdout.write(f'school_followups_synced={total} gandom_ready=1')
