"""Service breakdown of approved call-center deposits already on a visit."""

from collections import defaultdict
from decimal import Decimal

from django import forms

from .call_center_deposit_views import DEPOSIT_MARKER, DepositAmountField
from .models import AuditLog, FinancialTransaction

ZERO = Decimal("0")


def appointment_deposits(appointment_ids):
    return FinancialTransaction.objects.filter(
        appointment_id__in=appointment_ids, source="manual", entry_type="inc",
        raw_data__payment_kind=DEPOSIT_MARKER, review_status__in=("approved", "pending"),
    ).order_by("occurred_at", "pk")


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
        for item in self.items:
            self.fields[f"item_{item.pk}"] = DepositAmountField(
                label=item.title, required=False, min_value=ZERO,
                max_digits=15, decimal_places=0, max_value=item.line_total_toman,
                initial=self.summary["by_item"].get(item.pk, ZERO),
                widget=forms.TextInput(attrs={"inputmode": "numeric", "data-money-exempt": "1"}),
            )

    def clean(self):
        data = super().clean()
        total = sum((value or ZERO for value in data.values()), ZERO)
        if total > self.summary["approved"]:
            raise forms.ValidationError("جمع تخصیص بیشتر از بیعانهٔ تأییدشده است.")
        if total > self.plan.final_amount_toman:
            raise forms.ValidationError("جمع تخصیص بیشتر از مبلغ نهایی پکیج است.")
        return data

    def save(self, receipts, *, user, request_path):
        """Called with the visit and receipts locked in the surrounding transaction."""
        pending = {
            item.pk: self.cleaned_data[f"item_{item.pk}"] or ZERO
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
