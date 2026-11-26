"""Service breakdown of approved call-center deposits already on a visit."""

from collections import defaultdict
from decimal import Decimal

from django import forms
from django.db.models import Q

from .call_center_deposit_views import (
    DEPOSIT_MARKER, DepositMillionsField, deposit_patient_reference, legacy_toman_to_million,
)
from .device_pricing import MILLION, from_toman_to_million
from .models import AuditLog, FinancialTransaction

ZERO = Decimal("0")


def appointment_deposits(appointment_ids, *, patient_ids=()):
    scope = Q(appointment_id__in=appointment_ids)
    if patient_ids:
        scope |= Q(appointment__isnull=True, patient_ref__in=[
            deposit_patient_reference(pk) for pk in patient_ids
        ])
    return FinancialTransaction.objects.filter(
        scope, source="manual", entry_type="inc",
        raw_data__payment_kind=DEPOSIT_MARKER, review_status__in=("approved", "pending"),
    ).order_by("occurred_at", "pk")


def _normalized_name(name):
    spelling = str.maketrans({"ي": "ی", "ك": "ک", "\u200c": " "})
    return " ".join(name.translate(spelling).casefold().split())


def link_deposits_at_reception(appointment, patient, *, user, request_path):
    """Link each held receipt once, inside the transaction recording arrival."""
    if getattr(appointment.branch.country, "code", "") != "IR":
        return
    receipts = appointment_deposits((), patient_ids=(patient.pk,)).filter(
        branch__isnull=True, raw_data__country_code="IR",
    ).order_by("pk").select_for_update(of=("self",))
    name = _normalized_name(appointment.full_name)
    linked = []
    for receipt in receipts:
        same_lead = appointment.lead_id and receipt.raw_data.get("lead_id") == appointment.lead_id
        # A family can share one phone. A walk-in must also match the name on the receipt.
        if not same_lead and _normalized_name(receipt.person_name) != name:
            continue
        receipt.appointment = appointment
        receipt.branch = appointment.branch
        receipt.raw_data = {**receipt.raw_data, "appointment_id": appointment.pk}
        linked.append(receipt)
    if linked:
        FinancialTransaction.objects.bulk_update(linked, ["appointment", "branch", "raw_data"])
        AuditLog.objects.create(
            actor=user, action="call_center_deposit_link", path=request_path, method="POST",
            object_type="VisitAppointment", object_id=str(appointment.pk),
            summary="اتصال بیعانهٔ کال‌سنتر به مراجعه هنگام پذیرش",
            metadata={"receipts": [receipt.pk for receipt in linked], "patient_id": patient.pk},
        )


def _receipt_allocations(receipt):
    return receipt.raw_data.get("service_allocations", [])


def deposit_summary(receipts):
    approved = pending = ZERO
    by_item = defaultdict(lambda: ZERO)
    services = defaultdict(lambda: ZERO)
    for receipt in receipts:
        if receipt.review_status == "pending":
            pending += receipt.amount / 10
            continue
        approved += receipt.amount / 10
        for allocation in _receipt_allocations(receipt):
            amount = Decimal(allocation["amount_toman"])
            by_item[allocation["item_id"]] += amount
            services[allocation["title"]] += amount
    applied = sum(by_item.values(), ZERO)
    return {
        "approved": approved, "pending": pending, "applied": applied,
        "available": approved - applied, "by_item": by_item, "services": dict(services),
    }


class DepositAllocationForm(forms.Form):
    """One amount for each real included service in the current package."""

    def __init__(self, *args, plan, receipts, **kwargs):
        super().__init__(*args, **kwargs)
        self.plan = plan
        self.summary = deposit_summary(receipts)
        self.items = list(plan.included_items)
        if self.is_bound:
            self.data = self.data.copy()
        for item in self.items:
            name = f"item_million_{item.pk}"
            legacy_name = f"item_{item.pk}"
            self.fields[name] = DepositMillionsField(
                label=item.title, required=False, min_value=ZERO,
                max_value=item.line_total_toman / MILLION,
                initial=from_toman_to_million(self.summary["by_item"].get(item.pk, ZERO)),
            )
            if self.is_bound and name not in self.data and legacy_name in self.data:
                self.data[name] = legacy_toman_to_million(self.data[legacy_name])

    def clean(self):
        data = {key: ((value or ZERO) * MILLION).to_integral_exact() for key, value in super().clean().items()}
        total = sum(data.values(), ZERO)
        if total > self.summary["approved"]:
            raise forms.ValidationError("جمع تخصیص بیشتر از بیعانهٔ تأییدشده است.")
        if total > self.plan.final_amount_toman:
            raise forms.ValidationError("جمع تخصیص بیشتر از مبلغ نهایی پکیج است.")
        return data

    def save(self, receipts, *, user, request_path):
        """Called with the visit and receipts locked in the surrounding transaction."""
        pending = {
            item.pk: self.cleaned_data[f"item_million_{item.pk}"]
            for item in self.items
        }
        receipt_updates = []
        audit_allocations = []
        for receipt in receipts:
            remaining = receipt.amount / 10
            allocations = []
            for item in self.items:
                amount = min(remaining, pending[item.pk])
                if not amount:
                    continue
                allocations.append({
                    "item_id": item.pk, "title": item.title, "amount_toman": str(amount),
                })
                pending[item.pk] -= amount
                remaining -= amount
            if allocations == _receipt_allocations(receipt):
                continue
            receipt.raw_data = {**receipt.raw_data, "service_allocations": allocations}
            receipt_updates.append(receipt)
            audit_allocations.append({"receipt_id": receipt.pk, "services": allocations})
        if receipt_updates:
            FinancialTransaction.objects.bulk_update(receipt_updates, ["raw_data"])
            AuditLog.objects.create(
                actor=user, action="call_center_deposit_allocate", path=request_path, method="POST",
                object_type="ConsultationPlan", object_id=str(self.plan.pk),
                summary="تخصیص بیعانهٔ کال‌سنتر به خدمات پکیج",
                metadata={"allocations": audit_allocations},
            )
