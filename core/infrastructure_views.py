"""Read-only inventory plus append-only manual verification for authorised auditors."""
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from .infrastructure_models import InfrastructureBalanceCheck, InfrastructureService

AUDITOR_GROUP = "GreenLife Infrastructure Audit"


def can_audit_infrastructure(user):
    if not user.is_authenticated or not user.is_active:
        return False
    profile = getattr(user, "profile", None)
    if profile and not profile.is_active:
        return False
    return (
        user.is_superuser
        or bool(profile and profile.role == "admin")
        or user.groups.filter(name=AUDITOR_GROUP).exists()
    )


class BalanceCheckForm(forms.Form):
    service_id = forms.IntegerField(min_value=1)
    status = forms.ChoiceField(choices=InfrastructureBalanceCheck.STATUS_CHOICES)
    amount_due = forms.DecimalField(
        required=False, min_value=0, max_digits=17, decimal_places=0,
        label="بدهی (ریال)",
    )
    due_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    source = forms.ChoiceField(choices=InfrastructureBalanceCheck.SOURCE_CHOICES)
    note = forms.CharField(max_length=600, required=False, widget=forms.Textarea(attrs={"rows": 2}))

    def clean(self):
        data = super().clean()
        if data.get("status") == "owed" and data.get("amount_due") is None:
            self.add_error("amount_due", "برای بدهی، مبلغ را ثبت کنید.")
        if data.get("status") == "clear" and data.get("amount_due") not in (None, 0):
            self.add_error("amount_due", "برای وضعیت بدون بدهی، مبلغ باید صفر یا خالی باشد.")
        return data


@login_required
@require_http_methods(["GET", "POST"])
def infrastructure_dashboard(request):
    if not can_audit_infrastructure(request.user):
        raise PermissionDenied("دسترسی بررسی زیرساخت برای شما فعال نیست.")

    form = BalanceCheckForm()
    if request.method == "POST":
        form = BalanceCheckForm(request.POST)
        if form.is_valid():
            service = get_object_or_404(
                InfrastructureService, pk=form.cleaned_data["service_id"], is_active=True,
            )
            InfrastructureBalanceCheck.objects.create(
                service=service, checked_by=request.user,
                status=form.cleaned_data["status"],
                amount_due=form.cleaned_data["amount_due"],
                due_date=form.cleaned_data["due_date"],
                source=form.cleaned_data["source"],
                note=form.cleaned_data["note"],
            )
            messages.success(request, "نتیجه بررسی ثبت شد؛ این اطلاعات به‌صورت دستی اعلام شده است.")
            return redirect("infrastructure_dashboard")

    services = list(
        InfrastructureService.objects.filter(is_active=True)
        .select_related("branch")
        .prefetch_related(Prefetch(
            "balance_checks",
            queryset=InfrastructureBalanceCheck.objects.select_related("checked_by")
            .order_by("-checked_at", "-pk"),
            to_attr="recent_checks",
        ))
    )
    for service in services:
        service.latest_check = service.recent_checks[0] if service.recent_checks else None
    return render(request, "core/infrastructure_dashboard.html", {
        "services": services,
        "form": form,
        "can_add_service": (
            request.user.is_superuser
            or getattr(getattr(request.user, "profile", None), "role", "") == "admin"
        ),
    })
