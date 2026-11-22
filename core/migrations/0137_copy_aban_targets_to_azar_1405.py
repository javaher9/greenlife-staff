"""One-time requested rollover: Aban 1405 -> Azar 1405 sales targets.

Copy only goals missing in Azar. Never overwrite manually configured Azar goals.
Preserve previous months and financial transactions unchanged. This migration is
idempotent, and migration history prevents a repeated automatic rollover.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.db import migrations, transaction


SOURCE = (1405, 8)
DEST = (1405, 9)
ALLOWED_SCOPES = {"overall", "branch", "call_center", "flower"}
ONE_HUNDRED = Decimal("100")
Q = Decimal("0.01")


def copy_aban_to_azar(apps, schema_editor):
    using = schema_editor.connection.alias
    Band = apps.get_model("core", "SalesTargetBand")
    Policy = apps.get_model("core", "TargetPercentPolicy")
    Branch = apps.get_model("core", "Branch")
    Profile = apps.get_model("core", "EmployeeProfile")

    prior = Policy.objects.using(using).filter(
        period_year=SOURCE[0], period_month=SOURCE[1],
    ).first()
    current = Policy.objects.using(using).filter(
        period_year=DEST[0], period_month=DEST[1],
    ).first()
    copied_policy = False
    created = 0
    skipped = 0

    with transaction.atomic(using=using):
        if current is None and prior is not None:
            current, copied_policy = Policy.objects.using(using).get_or_create(
                period_year=DEST[0],
                period_month=DEST[1],
                defaults={
                    "heavy_percent": prior.heavy_percent,
                    "target_one_percent": prior.target_one_percent,
                    "target_two_percent": prior.target_two_percent,
                    "updated_by_id": None,
                },
            )
        h = current.heavy_percent if current else Decimal("70")
        t1 = current.target_one_percent if current else Decimal("130")
        t2 = current.target_two_percent if current else Decimal("160")
        active_branches = set(Branch.objects.using(using)
            .filter(is_active=True)
            .exclude(name__icontains="ارومیه")
            .exclude(name__icontains="افسریه")
            .values_list("pk", flat=True))
        active_flowers = set(Profile.objects.using(using)
            .filter(is_active=True, role="call_center", user__is_active=True)
            .values_list("user_id", flat=True))

        for old in Band.objects.using(using).filter(
            period_year=SOURCE[0], period_month=SOURCE[1],
        ).order_by("pk"):
            if old.scope not in ALLOWED_SCOPES:
                skipped += 1
                continue
            if old.scope == "branch" and old.branch_id not in active_branches:
                skipped += 1
                continue
            if old.scope == "flower" and old.employee_id not in active_flowers:
                skipped += 1
                continue

            # The stored subject identity remains stable across Jalali months.
            prefix = f"{SOURCE[0]}-{SOURCE[1]:02d}:"
            if not old.key.startswith(prefix):
                skipped += 1
                continue
            new_key = f"{DEST[0]}-{DEST[1]:02d}:" + old.key[len(prefix):]
            floor = old.sales_floor
            if floor is None or floor <= 0:
                skipped += 1
                continue
            _, was_created = Band.objects.using(using).get_or_create(
                key=new_key,
                defaults={
                    "period_year": DEST[0],
                    "period_month": DEST[1],
                    "scope": old.scope,
                    "branch_id": old.branch_id,
                    "employee_id": old.employee_id,
                    "heavy_limit": (floor * h / ONE_HUNDRED).quantize(Q, rounding=ROUND_HALF_UP),
                    "sales_floor": floor,
                    "target_one": (floor * t1 / ONE_HUNDRED).quantize(Q, rounding=ROUND_HALF_UP),
                    "target_two": (floor * t2 / ONE_HUNDRED).quantize(Q, rounding=ROUND_HALF_UP),
                    "updated_by_id": None,
                },
            )
            if was_created:
                created += 1
            else:
                skipped += 1

    print(f"Azar sales-target rollover: copied {created}, skipped {skipped}, copied prior percentage policy={copied_policy}")


class Migration(migrations.Migration):
    dependencies = [("core", "0136_one_time_200_new_leads_to_saturday_queue")]
    operations = [
        migrations.RunPython(copy_aban_to_azar, migrations.RunPython.noop),
    ]
