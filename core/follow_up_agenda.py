"""Call-center callback time and audit helpers.

Legacy rows have next_follow_up (date) but no time; never fabricate a time.
All new contact attempts write an independent history record. Appending a
history row does not move the lead to another operator or silently close it.
"""
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from .models import LeadFollowUpLog, ReferralLead


def previous_follow_up(lead):
    """A stable snapshot captured BEFORE ModelForm mutates the instance."""
    return {
        "date":lead.next_follow_up,
        "time":lead.next_follow_up_time,
        "result":lead.contact_result,
        "status":lead.status,
    }


def record_follow_up(lead, *, actor=None, previous, result=None, note=""):
    """Insert an audit event in the same transaction as the saved lead."""
    result=result if result is not None else lead.contact_result
    before_date=previous.get("date")
    changed_date=(before_date,previous.get("time")) != (lead.next_follow_up,lead.next_follow_up_time)
    if result == "no_answer":
        action="attempt"
    elif result == "follow_up" and lead.next_follow_up:
        action="scheduled"
    elif result in ("not_interested","appointment","won","sale_lost"):
        action="closed"
    else:
        action="updated"
    return LeadFollowUpLog.objects.create(
        lead=lead,actor=actor if getattr(actor,"is_authenticated",False) else None,
        action=action,result=result or "",
        previous_date=before_date,previous_time=previous.get("time"),
        scheduled_for=lead.next_follow_up,scheduled_time=lead.next_follow_up_time,
        note=(note or "")[:2000],
    )


def due_follow_up_scope(queryset):
    """Do not schedule callbacks for leads with terminal outcomes."""
    return queryset.exclude(status__in=("won","lost","visited")).exclude(
        contact_result__in=("won","sale_lost","not_interested")
    )


def local_due_time(lead):
    """'—' for legacy date-only promises instead of a made-up hour."""
    return lead.next_follow_up_time.strftime("%H:%M") if lead.next_follow_up_time else "—"
