"""One-time secure handover for Isfahan receptionist and consultant role accounts.

Password is read from stdin, NEVER passed in argv or committed to Git.
Run only from a trusted server-side process with tightly controlled input.
"""
import sys

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q

from core.credential_security import change_desktop_password
from core.models import Branch, EmployeeProfile, StaffCredential
from core.personnel_access import revoke_staff_sessions

SEATS=(
    ("esfahan.reception", "Esfehan.monshi", "منشی", "receptionist"),
    ("esfahan.consultant", "Esfehan.moshaver", "مشاور", "consultant"),
)


def normalized(text):
    return "".join((text or "").replace("ي","ی").replace("ك","ک").replace("\u200c","").lower().split())


class Command(BaseCommand):
    help="Rename the two Isfahan role logins and securely initialize their passwords from stdin."

    def add_arguments(self,parser):
        parser.add_argument("--password-stdin",action="store_true")

    def handle(self,*args,**options):
        if not options["password_stdin"] or sys.stdin.isatty():
            raise CommandError("Provide the credential only via a noninteractive stdin pipe.")
        password=sys.stdin.read().rstrip("\r\n")
        if len(password)<10 or not any(c.isalpha() for c in password) or not any(c.isdigit() for c in password) or "\n" in password or "\r" in password:
            raise CommandError("Credential fails minimum length/complexity checks.")
        with transaction.atomic():
            branches=[b for b in Branch.objects.filter(is_active=True) if normalized(b.name) in ("اصفهان","esfahan","isfahan")]
            if len(branches)!=1:
                raise CommandError("Exactly one active Isfahan branch must exist; no account changes made.")
            branch=branches[0]
            accounts=[]
            for old,new,first_name,role in SEATS:
                matches=list(User.objects.select_for_update().filter(
                    Q(username__iexact=old)|Q(username__iexact=new)
                ))
                if len(matches)>1:
                    raise CommandError(f"{new}: duplicate source/destination accounts; nothing changed.")
                if matches:
                    user=matches[0]
                    if user.is_superuser or user.is_staff:
                        raise CommandError(f"{new}: privileged username collision; nothing changed.")
                    existing_profile=EmployeeProfile.objects.filter(user=user).first()
                    if existing_profile and (existing_profile.role!=role or existing_profile.branch_id not in (None,branch.pk)):
                        raise CommandError(f"{new}: unexpected existing role/branch; nothing changed.")
                else:
                    user=User(username=new,is_staff=False,is_superuser=False)
                user.username=new
                user.first_name=first_name
                user.last_name="اصفهان"
                user.is_active=True
                user.save()
                profile,_=EmployeeProfile.objects.update_or_create(
                    user=user,
                    defaults=dict(
                        role=role,branch=branch,country=branch.country,
                        job_title=f"{first_name} اصفهان",is_active=True,
                        can_use_sales_network=False,
                        can_register_instagram_dm_lead=False,
                        remote_attendance_enabled=False,
                        can_request_payments=False,
                        can_execute_payments=False,
                        can_manage_petty_cash=False,
                        can_claim_personal_expense=False,
                    ),
                )
                change_desktop_password(user,password)
                credential=StaffCredential.objects.get(user=user)
                credential.mobile_pin_hash=""
                credential.mobile_pin_cipher=""
                credential.mobile_pin_set_at=None
                credential.mobile_failed_attempts=0
                credential.mobile_locked_until=None
                credential.save(update_fields=[
                    "mobile_pin_hash","mobile_pin_cipher","mobile_pin_set_at",
                    "mobile_failed_attempts","mobile_locked_until","updated_at",
                ])
                revoked=revoke_staff_sessions(user.pk)
                accounts.append((new,user.pk,profile.pk,revoked))
        # Never print supplied password, hashes, or encrypted credential values.
        for username,user_id,profile_id,revoked in accounts:
            self.stdout.write(f"{username}: ready user_id={user_id} profile_id={profile_id} sessions_revoked={revoked} desktop=enabled mobile_password_fallback=enabled")
