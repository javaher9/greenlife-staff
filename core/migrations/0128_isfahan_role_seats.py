"""Provision permanent Isfahan role seats, without embedding shared passwords.

These are *role* accounts, not substitutes for personal employee records.
They cannot sign in until an executive securely sets a desktop password
(and optionally a mobile PIN) in the existing credential settings screen.
"""

from django.db import migrations
from django.contrib.auth.hashers import make_password


ROLE_SEATS = (
    ("esfahan.reception", "منشی", "اصفهان", "receptionist"),
    ("esfahan.consultant", "مشاور", "اصفهان", "consultant"),
)


def _normalize(text):
    return "".join(
        (text or "")
        .replace("ي", "ی")
        .replace("ك", "ک")
        .replace("\u200c", "")
        .lower()
        .split()
    )


def provision_isfahan_role_seats(apps, schema_editor):
    User = apps.get_model("auth", "User")
    Branch = apps.get_model("core", "Branch")
    EmployeeProfile = apps.get_model("core", "EmployeeProfile")
    db = schema_editor.connection.alias

    matches = [
        branch
        for branch in Branch.objects.using(db).filter(is_active=True)
        if any(alias in _normalize(branch.name) for alias in ("اصفهان", "esfahan", "isfahan"))
    ]
    # Do not silently assign clinical permissions to a guessed branch.
    if len(matches) != 1:
        return
    branch = matches[0]

    for username, first_name, last_name, role in ROLE_SEATS:
        # Never take over an existing account, including case variants.
        if User.objects.using(db).filter(username__iexact=username).exists():
            continue

        user = User(
            username=username,
            first_name=first_name,
            last_name=last_name,
            is_active=True,
            is_staff=False,
            is_superuser=False,
            password=make_password(None),
        )
        user.save(using=db)

        EmployeeProfile.objects.using(db).create(
            user_id=user.pk,
            branch_id=branch.pk,
            country_id=branch.country_id,
            role=role,
            job_title=f"{first_name} {last_name}",
            is_active=True,
            can_use_sales_network=False,
            can_register_instagram_dm_lead=False,
            can_request_payments=False,
            can_execute_payments=False,
            can_manage_petty_cash=False,
            can_claim_personal_expense=False,
            remote_attendance_enabled=False,
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0127_menutritionprogress"),
    ]
    operations = [
        migrations.RunPython(
            provision_isfahan_role_seats,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
