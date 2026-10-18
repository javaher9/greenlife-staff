"""Safely redistribute Kameliya's open backlog; dry-run unless --execute."""
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.call_center_identity import call_center_display_name
from core.models import AuditLog, EmployeeProfile, ReferralLead, ReferralSale


class Command(BaseCommand):
    help = "Preview or redistribute Parisa Kolkoli's open leads to four active flowers."

    def add_arguments(self, parser):
        parser.add_argument('--execute', action='store_true', help='Commit reassignment (default: preview only)')
        parser.add_argument('--expected', type=int, default=64, help='Expected eligible count; execution stops if different')

    def handle(self, *args, **options):
        with transaction.atomic():
            profiles = list(EmployeeProfile.objects.select_related('user').filter(
                role='call_center', is_active=True, user__is_active=True,
            ))
            def matches(profile, fragments):
                identity = ' '.join((profile.user.first_name, profile.user.last_name, profile.user.username)).lower().replace('ي','ی').replace('ك','ک')
                return any(fragment in identity for fragment in fragments)
            sources = [p for p in EmployeeProfile.objects.select_related('user').all()
                       if matches(p, ('کلکلی','kolkoli','kalakali'))]
            if len(sources) != 1:
                raise CommandError(f'Expected exactly one Parisa Kolkoli profile; found {len(sources)}')
            names = [
                ('نرگس', ('بابایی','babaei','babayi','babaee')),
                ('بنفشه', ('توانا','tavana')),
                ('یاسمن', ('آزادی','ازادی','azadi')),
                ('خورشیدی', ('صالحی','salehi')),
            ]
            targets = []
            for label, aliases in names:
                found = [p for p in profiles if matches(p, aliases)]
                if len(found) != 1:
                    raise CommandError(f'{label}: expected one active profile, found {len(found)}')
                targets.append(found[0])
            source = sources[0]
            eligible = ReferralLead.objects.select_for_update().filter(
                assigned_to_id=source.pk, status__in=('new','contacted'),
                first_appointment_by__isnull=True,
            ).exclude(
                pk__in=ReferralSale.objects.filter(status__in=('approved','paid')).values('lead_id')
            ).order_by('created_at','pk')
            leads = list(eligible)
            count = len(leads)
            self.stdout.write(f'Eligible open leads: {count}; expected: {options["expected"]}')
            if count != options['expected']:
                raise CommandError('Eligible count differs; no changes made. Review backlog before retrying.')
            for i, (label, _) in enumerate(names):
                self.stdout.write(f'{label}: {sum(1 for j in range(count) if j % 4 == i)}')
            if not options['execute']:
                self.stdout.write('DRY RUN ONLY. No records changed. Use --execute after reviewing.')
                return
            from core.referral_views import _default_call_center_group
            now = timezone.now()
            for index, lead in enumerate(leads):
                target = targets[index % len(targets)]
                group = _default_call_center_group(target)
                changed = ReferralLead.objects.filter(
                    pk=lead.pk, assigned_to_id=source.pk,
                    status__in=('new','contacted'), first_appointment_by__isnull=True,
                ).update(assigned_to_id=target.pk, assigned_at=now, group_id=group.pk)
                if changed != 1:
                    raise CommandError(f'Concurrent modification for lead {lead.pk}; rolled back')
                AuditLog.objects.create(
                    actor=None, action='lead_reassign', path='management:redistribute_kolkoli_leads',
                    method='COMMAND', object_type='ReferralLead', object_id=str(lead.pk),
                    summary=f'Backlog transfer: {call_center_display_name(source)} -> {label}',
                    metadata={'from_operator':source.pk,'to_operator':target.pk,
                              'reason':'former staff backlog','batch':'kolkoli-2026-10'},
                )
            self.stdout.write(self.style.SUCCESS(f'Reassigned {count} leads; transaction committed.'))
