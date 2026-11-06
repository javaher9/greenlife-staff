"""Merge the two explicitly approved duplicate call-center groups.

Read-only by default. Run --apply only after reviewing the dry-run output and
taking a database backup. Since SMS segments use leadgroup:<pk>, retain the
canonical row's PK and reassign all leads before removing its alias.
"""
from django.core.management.base import BaseCommand
from django.db import transaction
from core.models import CallCenterLeadGroup, ReferralLead

PAIRS = (
    ("وب‌سایت", ("وب سایت", "وبسایت", "وب‌سایت")),
    ("مربی قدیمی دکتر جواهریان", ("مربی قدیمی دکتر", "مربی قدیمی دکتر جواهریان")),
)


class Command(BaseCommand):
    help = "Preview or apply safe deduplication of two call-center groups."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Commit the merge; default is dry-run.")

    def handle(self, *args, **options):
        apply = options["apply"]
        with transaction.atomic():
            for canonical_name, aliases in PAIRS:
                groups = list(
                    CallCenterLeadGroup.objects.select_for_update()
                    .filter(name__in=aliases).order_by("id")
                )
                if not groups:
                    self.stdout.write(f"NOT FOUND: {canonical_name}")
                    continue
                canonical = next((g for g in groups if g.name == canonical_name), groups[0])
                duplicates = [g for g in groups if g.pk != canonical.pk]
                affected = ReferralLead.objects.filter(group_id__in=[g.pk for g in duplicates]).count()
                self.stdout.write(
                    f"{canonical_name}: keep id={canonical.pk}; "
                    f"merge ids={[g.pk for g in duplicates]}; leads to move={affected}"
                )
                if not apply:
                    continue
                # Keep the existing canonical ID stable for SMS saved segment keys.
                if canonical.name != canonical_name:
                    # Any canonical-name collision would have been included in groups.
                    canonical.name = canonical_name
                    canonical.save(update_fields=["name"])
                if any(g.is_default for g in groups) and not canonical.is_default:
                    canonical.is_default = True
                    canonical.save(update_fields=["is_default"])
                if duplicates:
                    ReferralLead.objects.filter(group_id__in=[g.pk for g in duplicates]).update(group=canonical)
                    # Do not delete a group if another model still references it.
                    # Django's protected references will stop the transaction safely.
                    CallCenterLeadGroup.objects.filter(pk__in=[g.pk for g in duplicates]).delete()
            if not apply:
                self.stdout.write("DRY RUN ONLY. No data changed. Use --apply after backup.")
            else:
                self.stdout.write(self.style.SUCCESS("Merge committed. Verify call center and SMS groups."))
