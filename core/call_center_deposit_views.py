"""Restricted desktop entry of real call-center advance payments.

Registrars can only CREATE pending receipts; approval remains executive-only.
No data migration or changes to original finance totals are required.
"""
import uuid
from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache

from .call_center_identity import call_center_display_name
from .models import AuditLog, EmployeeProfile, FinancialTransaction, StaffNotification, VisitAppointment


DEPOSIT_MARKER = "call_center_deposit"
DEPOSIT_HEADING = "بیعانه کال‌سنتر"


def is_deposit_registrar(user):
    """Single named QC operator or explicitly granted registrar group."""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False
    profile = getattr(user, "profile", None)
    if not profile or not profile.is_active or profile.role != "quality_control":
        return False
    last_name = (user.last_name or "").replace("ي", "ی").replace("ك", "ک").strip()
    return last_name == "نادری" or user.groups.filter(
        name="GreenLife CallCenter Deposit Registrar",
    ).exists()


def is_call_center_deposit(item):
    return (
        item.source == "manual"
        and (item.raw_data or {}).get("payment_kind") == DEPOSIT_MARKER
    )


class CallCenterDepositForm(forms.Form):
    appointment = forms.ModelChoiceField(
        label="مراجع و نوبت کال‌سنتر",
        queryset=VisitAppointment.objects.none(),
        empty_label="نوبت ثبت‌شده را انتخاب کنید",
    )
    amount_toman = forms.DecimalField(
        label="مبلغ بیعانه (تومان)", min_value=Decimal("1"),
        max_digits=16, decimal_places=0,
        widget=forms.NumberInput(attrs={"min": "1", "step": "1", "inputmode": "numeric"}),
    )
    payment_method = forms.ChoiceField(
        label="روش دریافت",
        choices=(
            ("Pos S", "Pos S"), ("Pos H", "Pos H"),
            ("CC P", "CC P"), ("CC D", "CC D"), ("CC S", "CC S"),
            ("LINK", "لینک پرداخت"), ("TRANSFER", "کارت‌به‌کارت / حواله"),
        ),
    )
    tracking_number = forms.CharField(label="شماره پیگیری پرداخت", max_length=100)
    receipt_image = forms.ImageField(label="تصویر رسید پرداخت")
    description = forms.CharField(
        label="توضیحات (اختیاری)", max_length=250, required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    submission_token = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["appointment"].queryset = (
            VisitAppointment.objects.filter(
                branch__country__code="IR", source="call_center",
                lead__isnull=False,
            ).exclude(status__in=("cancelled", "no_show"))
            .select_related("lead__first_appointment_by", "created_by", "branch")
        )
        if not self.is_bound:
            self.fields["submission_token"].initial = uuid.uuid4()

    def clean_receipt_image(self):
        image = self.cleaned_data["receipt_image"]
        if image.size > 8 * 1024 * 1024:
            raise forms.ValidationError("تصویر رسید باید کمتر از ۸ مگابایت باشد.")
        return image

    def clean_appointment(self):
        item = self.cleaned_data["appointment"]
        lead = item.lead
        owner_id = lead.first_appointment_by_id or item.created_by_id
        if not owner_id or not EmployeeProfile.objects.filter(
            user_id=owner_id, role="call_center",
        ).exists():
            raise forms.ValidationError(
                "مالک گل کال‌سنتر برای این نوبت مشخص نیست؛ ابتدا انتساب نوبت را اصلاح کنید."
            )
        return item

    def clean(self):
        data = super().clean()
        tracking = (data.get("tracking_number") or "").strip()
        method = data.get("payment_method")
        if tracking and method and FinancialTransaction.objects.filter(
            source="manual", entry_type="inc",
            payment_method=method, tracking_number=tracking,
            review_status__in=("pending", "approved"),
        ).exists():
            self.add_error(
                "tracking_number",
                "این شماره پیگیری قبلاً ثبت شده است؛ از ثبت بیعانه تکراری جلوگیری شد.",
            )
        return data


@never_cache
@login_required
def call_center_deposit_entry(request):
    from .views import _is_mobile_request

    if not is_deposit_registrar(request.user):
        raise PermissionDenied("ثبت بیعانه فقط برای مسئول تعیین‌شده کال‌سنتر فعال است.")
    if _is_mobile_request(request):
        raise PermissionDenied("ثبت بیعانه فقط در فضای دسکتاپ کال‌سنتر فعال است.")

    search = (request.GET.get("q") or "").strip()[:80]
    matches = []
    if search:
        matches = list(
            VisitAppointment.objects.filter(
                branch__country__code="IR",
                source="call_center", lead__isnull=False,
            ).exclude(status__in=("cancelled", "no_show"))
            .filter(
                Q(full_name__icontains=search) | Q(phone__icontains=search)
                | Q(lead__phone__icontains=search)
            ).select_related(
                "lead", "lead__first_appointment_by", "branch", "created_by",
            ).order_by("-appointment_date", "-id")[:30]
        )
    form = CallCenterDepositForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        chosen = form.cleaned_data["appointment"]
        token = form.cleaned_data["submission_token"]
        external_id = f"ccdep:{request.user.pk}:{token.hex}"
        previous = FinancialTransaction.objects.filter(
            source="manual", external_id=external_id,
            recorded_by=request.user,
        ).first()
        if previous:
            messages.info(request, "این بیعانه قبلاً ثبت شده است و مجدد ذخیره نشد.")
            return redirect("call_center_deposit_entry")

        lead = chosen.lead
        owner_id = lead.first_appointment_by_id or chosen.created_by_id
        amount_rial = form.cleaned_data["amount_toman"] * Decimal("10")
        try:
            with transaction.atomic():
                item = FinancialTransaction.objects.create(
                    source="manual", external_id=external_id,
                    branch=chosen.branch, appointment=chosen,
                    occurred_at=timezone.now(), amount=amount_rial,
                    entry_type="inc", review_status="pending",
                    analysis_status="skipped",
                    person_name=chosen.full_name, patient_ref=str(lead.pk),
                    sale_origin="afsariyeh", sale_reason="other",
                    service=DEPOSIT_HEADING, account_heading=DEPOSIT_HEADING,
                    payment_method=form.cleaned_data["payment_method"],
                    tracking_number=form.cleaned_data["tracking_number"].strip(),
                    receipt_image=form.cleaned_data["receipt_image"],
                    description=(form.cleaned_data.get("description") or "").strip(),
                    call_center_owner_id=owner_id,
                    recorded_by=request.user,
                    raw_data={
                        "payment_kind": DEPOSIT_MARKER,
                        "entry_channel": "qc_desktop",
                        "lead_id": lead.pk,
                        "appointment_id": chosen.pk,
                        "first_appointment_owner_id": owner_id,
                        "amount_toman": str(form.cleaned_data["amount_toman"]),
                        "submission_token": token.hex,
                        "approval_required": "executive",
                    },
                )
                AuditLog.objects.create(
                    actor=request.user, action="call_center_deposit_entry",
                    path=request.path, method="POST",
                    object_type="FinancialTransaction", object_id=str(item.pk),
                    summary=f"ثبت بیعانه کال‌سنتر - {chosen.full_name}"[:250],
                    metadata={
                        "status": "pending", "amount_rial": str(amount_rial),
                        "lead_id": lead.pk, "appointment_id": chosen.pk,
                        "owner_id": owner_id, "branch_id": chosen.branch_id,
                    },
                )
                usernames = getattr(settings, "EXECUTIVE_USERNAMES", ())
                recipients = User.objects.filter(
                    username__in=usernames, is_active=True,
                ).distinct()
                for recipient in recipients:
                    StaffNotification.objects.create(
                        user=recipient,
                        title="بیعانه کال‌سنتر در انتظار تأیید شما",
                        message=f"{chosen.full_name} · {form.cleaned_data['amount_toman']} تومان",
                        notification_type="finance_review",
                        related_date=timezone.localdate(),
                    )
        except IntegrityError:
            messages.info(request, "این بیعانه قبلاً ثبت شده است.")
            return redirect("call_center_deposit_entry")
        messages.success(request, "بیعانه ثبت شد و برای تأیید مدیرعامل در صف مالی قرار گرفت.")
        return redirect("call_center_deposit_entry")

    recent = (
        FinancialTransaction.objects.filter(
            source="manual", recorded_by=request.user,
            raw_data__payment_kind=DEPOSIT_MARKER,
        ).select_related("branch", "call_center_owner")
        .order_by("-created_at")[:15]
    )
    response = render(request, "core/call_center_deposit_entry.html", {
        "form": form, "matches": matches, "search": search,
        "recent": recent, "flower_name": call_center_display_name,
    })
    response["Cache-Control"] = "private, no-store"
    return response
