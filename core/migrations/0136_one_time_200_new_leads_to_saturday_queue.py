"""One-off management request: return the latest 200 untouched call-center leads
to the existing unassigned morning queue on Friday 2026-11-20 (Tehran).

No schema changes. Never touch leads with any logged call/appointment/sale or
a promised callback. The production deployment already backs up the DB before
migrations. Migration recording guarantees this action is not replayed.
"""
from datetime import datetime

from django.conf import settings
from django.db import migrations, transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone


BATCH_KEY = "management-requeue-new-200-2026-11-20"
MAX_LEADS = 200


def requeue_latest_untouched(apps, schema_editor):
    # A single deployment-window permission, never a recurring Friday policy.
    # Tests (DEBUG=True) and later staging/re-deploys cannot mass-edit leads.
    if settings.DEBUG:
        print(f"{BATCH_KEY}: DEBUG mode; no live leads modified")
        return
    local_now = timezone.localtime()
    start = datetime(2026, 11, 20, 18, 0, tzinfo=local_now.tzinfo)
    end = datetime(2026, 11, 21, 8, 0, tzinfo=local_now.tzinfo)
    if not start <= local_now < end:
        print(f"{BATCH_KEY}: outside the approved evening/overnight window; skipped")
        return

    Lead = apps.get_model("core", "ReferralLead")
    FollowUp = apps.get_model("core", "LeadFollowUpLog")
    Appointment = apps.get_model("core", "VisitAppointment")
    Sale = apps.get_model("core", "ReferralSale")
    Audit = apps.get_model("core", "AuditLog")
    alias = schema_editor.connection.alias

    with transaction.atomic(using=alias):
        # Selection is global across *all* call-center flowers (Narges,
        # Banafsheh, Yasaman, Khorshidi, Laleh, etc.), newest first.
        # Exclude even unrecorded-result attempts when a callback-history
        # record exists. The model cannot infer unlogged actual phone calls.
        eligible = (
            Lead.objects.using(alias)
            .filter(
                status="new",
                contact_result="",
                assigned_to__isnull=False,
                assigned_to__role="call_center",
                next_follow_up__isnull=True,
                next_follow_up_time__isnull=True,
                first_appointment_by__isnull=True,
                school_enrollment__isnull=True,
            )
            .filter(~Exists(FollowUp.objects.using(alias).filter(lead_id=OuterRef("pk"))))
            .filter(~Exists(Appointment.objects.using(alias).filter(lead_id=OuterRef("pk"))))
            .filter(~Exists(Sale.objects.using(alias).filter(lead_id=OuterRef("pk"))))
            .select_for_update(of=("self",))
            .order_by("-created_at", "-pk")
        )
        selected = list(
            eligible.values(
                "pk", "assigned_to_id", "assigned_at", "group_id", "created_at"
            )[:MAX_LEADS]
        )
        if not selected:
            print(f"{BATCH_KEY}: no safe eligible leads found; zero updated")
            return

        # Audit before clearing ownership. Group and original lead text are
        # preserved; 'new' and any existing notes remain unchanged.
        audit = []
        for item in selected:
            audit.append(Audit(
                actor_id=None,
                action="bulk_unassign",
                path="/ops/one-time-requeue-20261120/",
                method="SYSTEM",
                object_type="ReferralLead",
                object_id=str(item["pk"]),
                summary="بدون مسئول تا توزیع صبح شنبه؛ دستور مدیریت",
                metadata={
                    "batch": BATCH_KEY,
                    "previous_assignee_id": item["assigned_to_id"],
                    "previous_assigned_at": (
                        item["assigned_at"].isoformat()
                        if item["assigned_at"] else None
                    ),
                    "preserved_group_id": item["group_id"],
                },
            ))

        ids = [item["pk"] for item in selected]
        updated = Lead.objects.using(alias).filter(
            pk__in=ids,
            status="new",
            contact_result="",
            assigned_to__isnull=False,
        ).update(assigned_to_id=None, assigned_at=None)
        if updated != len(ids):
            raise RuntimeError(
                f"{BATCH_KEY}: concurrent lead change detected; rollback entire batch"
            )

        audit.append(Audit(
            actor_id=None,
            action="bulk_unassign",
            path="/ops/one-time-requeue-20261120/",
            method="SYSTEM",
            object_type="ReferralLeadBatch",
            object_id=BATCH_KEY,
            summary=f"One-time Friday unassignment: {updated} new leads, Saturday queue",
            metadata={
                "batch": BATCH_KEY,
                "requested": MAX_LEADS,
                "updated": updated,
                "lead_ids": ids,
                "tehran_time": local_now.isoformat(),
                "release": "existing Saturday morning lead-routing worker",
            },
        ))
        Audit.objects.using(alias).bulk_create(audit)
        print(f"{BATCH_KEY}: safely unassigned {updated} leads; audit records saved")


class Migration(migrations.Migration):
    dependencies = [("core", "0135_call_center_group_guidance")]
    operations = [
        migrations.RunPython(requeue_latest_untouched, migrations.RunPython.noop)
    ]
