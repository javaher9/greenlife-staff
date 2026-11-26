"""Register call-center deposits through the existing executive review queue."""

import uuid
from decimal import Decimal

from django import forms
from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connection, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from .jalali import LATIN_DIGITS
from .models import (
    AuditLog, EmployeeProfile, FinancialTransaction, ReferralLead,
    StaffNotification, VisitAppointment,
)

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


def can_register_own_deposit(user):
    profile = getattr(user, "profile", None)
    return bool(user.is_active and profile and profile.is_active and profile.role == "call_center")


def is_call_center_deposit(item):
    return (
        item.source == "manual"
        and (item.raw_data or {}).get("payment_kind") == DEPOSIT_MARKER
    )


def _appointments():
    return VisitAppointment.objects.filter(
        branch__country__code="IR", source="call_center", lead__isnull=False,
    ).exclude(status__in=("cancelled", "no_show")).select_related(
        "lead__first_appointment_by", "created_by", "branch",
    )


class DepositAmountField(forms.DecimalField):
    def to_python(self, value):
        if isinstance(value, str):
            value = value.translate(LATIN_DIGITS).replace("٬", "").replace(",", "").strip()
        return super().to_python(value)


class CallCenterDepositForm(forms.Form):
    appointment = forms.ModelChoiceField(
        label="نوبت مراجع", queryset=VisitAppointment.objects.none(),
        empty_label="نوبت ثبت‌شده را انتخاب کنید",
    )
    amount_toman = DepositAmountField(
        label="مبلغ بیعانه (تومان)", min_value=Decimal("1"),
        max_digits=15, decimal_places=0,
        widget=forms.TextInput(attrs={
            "inputmode": "numeric", "placeholder": "مثلاً ۵۰٬۰۰۰٬۰۰۰", "data-money-exempt": "1",
        }),
    )
    payment_method = forms.ChoiceField(
        label="روش دریافت",
        choices=(
            ("", "روش دریافت را انتخاب کنید"),
            ("Pos S", "Pos S"), ("Pos H", "Pos H"), ("CC G", "CC G"),
            ("CC P", "CC P"), ("CC D", "CC D"), ("CC S", "CC S"),
            ("LINK", "لینک پرداخت"), ("TRANSFER", "کارت‌به‌کارت / حواله"),
        ),
    )
    tracking_number = forms.CharField(
        label="شماره پیگیری پرداخت", max_length=100,
        widget=forms.TextInput(attrs={"data-money-exempt": "1", "dir": "ltr"}),
    )
    receipt_image = forms.ImageField(label="تصویر رسید پرداخت")
    description = forms.CharField(
        label="توضیحات (اختیاری)", max_length=250, required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
    )
    submission_token = forms.UUIDField(widget=forms.HiddenInput)

    def __init__(self, *args, appointments, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["appointment"].queryset = appointments
        self.fields["appointment"].label_from_instance = lambda item: f"{item.branch.name}، {item}"
        if not self.is_bound:
            self.fields["submission_token"].initial = uuid.uuid4()

    def clean_tracking_number(self):
        return self.cleaned_data["tracking_number"].translate(LATIN_DIGITS).strip()

    def clean_receipt_image(self):
        image = self.cleaned_data["receipt_image"]
        if image.size > 8 * 1024 * 1024:
            raise forms.ValidationError("تصویر رسید باید کمتر از ۸ مگابایت باشد.")
        return image


def lock_deposit_tracking(method, tracking):
    if connection.vendor == "postgresql":
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)",
                [f"greenlife-deposit:{method}:{tracking.casefold()}"],
            )


def tracking_in_use(method, tracking, *, exclude_pk=None):
    return FinancialTransaction.objects.filter(
        source="manual", entry_type="inc", payment_method=method, tracking_number__iexact=tracking,
        review_status__in=("pending", "approved"),
    ).exclude(pk=exclude_pk).exists()


@transaction.atomic
def _save_deposit(request, form, lead=None):
    """Recheck scope under a lock before accepting the receipt."""
    data = form.cleaned_data
    appointments = _appointments().select_for_update(of=("self",))
    if lead:
        appointments = appointments.filter(lead=lead)
    chosen = get_object_or_404(appointments, pk=data["appointment"].pk)
    if lead:
        get_object_or_404(
            ReferralLead.objects.select_for_update(of=("self",)), pk=lead.pk,
            assigned_to__user=request.user, assigned_to__is_active=True,
            assigned_to__role="call_center",
        )
    first_owner_id = chosen.lead.first_appointment_by_id or chosen.created_by_id
    owner_id = request.user.pk if lead else first_owner_id
    if not lead and not EmployeeProfile.objects.filter(user_id=owner_id, role="call_center").exists():
        form.add_error("appointment", "مالک گل کال‌سنتر برای این نوبت مشخص نیست.")
        return False

    token = data["submission_token"].hex
    external_id = f"ccdep:{request.user.pk}:{token}"
    tracking, method = data["tracking_number"], data["payment_method"]
    lock_deposit_tracking(method, tracking)
    manual = FinancialTransaction.objects.filter(source="manual", entry_type="inc")
    if manual.filter(external_id=external_id).exists():
        messages.info(request, "این بیعانه قبلاً ثبت شده است.")
        return True
    if tracking_in_use(method, tracking):
        form.add_error("tracking_number", "این شماره پیگیری قبلاً ثبت شده است.")
        return False

    amount_rial = data["amount_toman"] * Decimal("10")
    item = manual.create(
        source="manual", external_id=external_id,
        branch=chosen.branch, appointment=chosen,
        occurred_at=timezone.now(), amount=amount_rial,
        entry_type="inc", review_status="pending", analysis_status="skipped",
        person_name=chosen.full_name, patient_ref=str(chosen.lead_id),
        sale_origin="afsariyeh", sale_reason="other",
        service=DEPOSIT_HEADING, account_heading=DEPOSIT_HEADING,
        payment_method=method, tracking_number=tracking, receipt_image=data["receipt_image"],
        description=data["description"], call_center_owner_id=owner_id, recorded_by=request.user,
        raw_data={
            "payment_kind": DEPOSIT_MARKER,
            "entry_channel": "call_center_operator" if lead else "qc_desktop",
            "lead_id": chosen.lead_id,
            "appointment_id": chosen.pk,
            "first_appointment_owner_id": first_owner_id,
            "amount_toman": str(data["amount_toman"]),
            "submission_token": token,
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
            "lead_id": chosen.lead_id, "appointment_id": chosen.pk,
            "owner_id": owner_id, "branch_id": chosen.branch_id,
        },
    )
    recipients = User.objects.filter(
        username__in=settings.EXECUTIVE_USERNAMES, is_active=True,
    )
    StaffNotification.objects.bulk_create([
        StaffNotification(
            user=recipient, title="بیعانه کال‌سنتر در انتظار تأیید شما",
            message=f"{chosen.full_name}، {data['amount_toman']:,} تومان",
            notification_type="finance_review", related_date=timezone.localdate(),
        )
        for recipient in recipients
    ])
    messages.success(request, "بیعانه برای این مراجع ثبت شد و در انتظار تأیید مدیرعامل است.")
    return True


def _deposit_page(request, *, appointments, matches, search="", lead=None):
    is_post = request.method == "POST"
    form = CallCenterDepositForm(
        request.POST if is_post else None, request.FILES if is_post else None,
        appointments=appointments.filter(pk__in=[item.pk for item in matches]),
        initial={"appointment": matches[0].pk} if lead and len(matches) == 1 else None,
    )
    if is_post and form.is_valid():
        data = form.cleaned_data
        external_id = f"ccdep:{request.user.pk}:{data['submission_token'].hex}"
        try:
            saved = _save_deposit(request, form, lead)
        except IntegrityError:
            # Other failures must surface normally; a concurrent replay can
            # legitimately hit the receipt's unique submission key.
            if not FinancialTransaction.objects.filter(source="manual", external_id=external_id).exists():
                raise
            messages.info(request, "این بیعانه قبلاً ثبت شده است.")
            saved = True
        if saved:
            if lead:
                return redirect("call_center_lead_deposit", pk=lead.pk)
            return redirect("call_center_deposit_entry")

    recent = FinancialTransaction.objects.filter(
        source="manual", recorded_by=request.user, raw_data__payment_kind=DEPOSIT_MARKER,
    )
    if lead:
        recent = recent.filter(appointment__lead=lead)
    return render(request, "core/call_center_deposit_entry.html", {
        "form": form, "matches": matches, "search": search, "lead": lead,
        "recent": recent.select_related("branch").order_by("-created_at")[:15],
        "appointment_url": reverse("appointment_schedule") + f"?lead={lead.pk}" if lead else "",
    })


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def call_center_deposit_entry(request):
    from .views import _is_mobile_request

    if not is_deposit_registrar(request.user):
        raise PermissionDenied("ثبت بیعانه فقط برای مسئول تعیین‌شده کال‌سنتر فعال است.")
    if _is_mobile_request(request):
        raise PermissionDenied("ثبت بیعانه فقط در فضای دسکتاپ کنترل کیفیت فعال است.")
    search = (request.GET.get("q") or request.POST.get("q") or "").strip()[:80]
    appointments = _appointments()
    matches = list(appointments.filter(
        Q(full_name__icontains=search) | Q(phone__icontains=search) | Q(lead__phone__icontains=search)
    ).order_by("-appointment_date", "-id")[:30]) if search else []
    return _deposit_page(request, appointments=appointments, matches=matches, search=search)


@never_cache
@login_required
@require_http_methods(["GET", "POST"])
def call_center_lead_deposit(request, pk):
    if not can_register_own_deposit(request.user):
        raise PermissionDenied("ثبت بیعانه این بخش فقط برای گل کال‌سنتر فعال است.")
    lead = get_object_or_404(ReferralLead, pk=pk, assigned_to=request.user.profile)
    appointments = _appointments().filter(lead=lead)
    matches = list(appointments.order_by("-appointment_date", "-appointment_time", "-id"))
    return _deposit_page(request, appointments=appointments, matches=matches, lead=lead)
