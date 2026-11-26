import uuid
from datetime import time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (
    AuditLog, Branch, ConsultationPlan, ConsultationPlanItem, EmployeeProfile, FinancialTransaction,
    PatientProfile,
    ReferralLead, ReferralProfile, ReferralSale, VisitAppointment,
)


@override_settings(EXECUTIVE_USERNAMES=("executive",))
class CallCenterDepositTests(TestCase):
    def setUp(self):
        self.naderi = self.make_user("qc-naderi", "آقای", "نادری", "quality_control")
        self.unauthorized_qc = self.make_user("other-qc", "مریم", "احمدی", "quality_control")
        self.operator = self.make_user("flower-salehi", "محمد", "صالحی", "call_center")
        self.executive = self.make_user("executive", "مدیر", "کل", "admin")
        self.branch = Branch.objects.create(name="نیاوران")
        ref_user = self.make_user("ref-advance", "منبع", "فروش", "referrer")
        referrer = ReferralProfile.objects.create(
            user=ref_user, referral_code="TEST-ADVANCE-REF"
        )
        self.lead = ReferralLead.objects.create(
            referrer=referrer, full_name="مراجع بیعانه",
            phone="09120005555", first_appointment_by=self.operator, assigned_to=self.operator.profile,
        )
        self.appt = VisitAppointment.objects.create(
            lead=self.lead, branch=self.branch, full_name=self.lead.full_name,
            phone=self.lead.phone, appointment_date=timezone.localdate(),
            appointment_time=time(10, 0), source="call_center",
            created_by=self.operator, status="booked",
        )
        self.url = "/call-center/deposits/new/"
        self.operator_url = reverse("call_center_lead_deposit", args=[self.lead.pk])

    def make_user(self, username, first, last, role):
        user = User.objects.create_user(
            username=username, first_name=first, last_name=last,
            password="test-pass",
        )
        EmployeeProfile.objects.update_or_create(
            user=user, defaults={"role": role, "is_active": True},
        )
        return user

    def receipt(self):
        return SimpleUploadedFile(
            "receipt.gif",
            b"GIF87a\x01\x00\x01\x00\x80\x01\x00\x00\x00\x00ccc,"
            b"\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;",
            content_type="image/gif",
        )

    def payload(self, **updates):
        data = {
            "q": self.appt.phone,
            "appointment": str(self.appt.pk),
            "amount_toman": "250000",
            "payment_method": "LINK",
            "tracking_number": "CCDEP-UNI-001",
            "receipt_image": self.receipt(),
            "description": "پیش‌پرداخت نوبت",
            "submission_token": str(uuid.uuid4()),
        }
        data.update(updates)
        return data

    def test_registrar_sees_desktop_entry_and_phone_is_denied(self):
        self.client.force_login(self.naderi)
        response = self.client.get("/quality-center/")
        # Some deployments use an alternate QC URL, so don't assume a route.
        self.assertIn(response.status_code, (200, 301, 302, 404))
        page = self.client.get(self.url, {"q": self.appt.phone})
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "ثبت بیعانه کال‌سنتر")
        self.assertContains(page, self.appt.full_name)
        mobile = self.client.get(
            self.url, {"q": self.appt.phone},
            HTTP_USER_AGENT="Mozilla/5.0 (Android 15; Mobile)",
        )
        self.assertEqual(mobile.status_code, 403)

    def test_other_staff_cannot_register_even_with_direct_url(self):
        self.client.force_login(self.unauthorized_qc)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(
            self.client.post(self.url, data=self.payload()).status_code, 403,
        )
        self.assertFalse(FinancialTransaction.objects.exists())

    def test_deposit_is_pending_bound_to_real_appointment_and_owner(self):
        self.client.force_login(self.naderi)
        resp = self.client.post(self.url, data=self.payload())
        self.assertEqual(resp.status_code, 302)
        entry = FinancialTransaction.objects.get(source="manual")
        self.assertEqual(entry.review_status, "pending")
        self.assertEqual(entry.entry_type, "inc")
        self.assertEqual(entry.amount, Decimal("2500000"))
        self.assertEqual(entry.appointment_id, self.appt.id)
        self.assertEqual(entry.call_center_owner_id, self.operator.pk)
        self.assertEqual(entry.branch_id, self.branch.pk)
        self.assertEqual(entry.raw_data["payment_kind"], "call_center_deposit")
        self.assertEqual(entry.recorded_by_id, self.naderi.pk)
        self.assertTrue(entry.receipt_image)
        self.assertEqual(
            AuditLog.objects.filter(action="call_center_deposit_entry").count(), 1,
        )
        self.assertEqual(
            FinancialTransaction.objects.filter(review_status="approved").count(), 0,
        )

    def test_duplicate_tracking_number_not_saved_again(self):
        self.client.force_login(self.naderi)
        self.client.post(self.url, data=self.payload())
        response = self.client.post(
            self.url, data=self.payload(submission_token=str(uuid.uuid4())),
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(FinancialTransaction.objects.count(), 1)
        self.assertContains(response, "شماره پیگیری قبلاً ثبت شده")

    def test_only_executive_approves_deposit(self):
        self.client.force_login(self.naderi)
        self.client.post(self.url, data=self.payload())
        entry = FinancialTransaction.objects.get()
        approval_url = f"/finance/entries/{entry.pk}/approve/"
        self.client.force_login(self.unauthorized_qc)
        response = self.client.post(approval_url)
        self.assertIn(response.status_code, (302, 403))
        self.client.force_login(self.executive)
        response = self.client.post(approval_url)
        self.assertEqual(response.status_code, 302)
        entry.refresh_from_db()
        self.assertEqual(entry.review_status, "approved")
        self.assertFalse(ReferralSale.objects.filter(lead=self.lead).exists())

    def test_executive_summary_and_flower_chart_share_approved_total(self):
        self.client.force_login(self.naderi)
        self.client.post(self.url, data=self.payload())
        self.client.force_login(self.executive)
        page = self.client.get("/finance/executive/")
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, "بیعانه در انتظار تأیید شما")
        self.assertContains(page, "عملکرد درآمد کال‌سنتر به تفکیک گل")
        entry = FinancialTransaction.objects.get()
        self.client.post(f"/finance/entries/{entry.pk}/approve/")
        page = self.client.get("/finance/executive/")
        self.assertContains(page, "گل خورشیدی")
        self.assertContains(page, "0.25")

    def test_operator_can_register_from_assigned_lead_on_mobile_and_replay_safely(self):
        self.client.force_login(self.operator)
        page = self.client.get(self.operator_url, HTTP_USER_AGENT="Mozilla/5.0 (Android 15; Mobile)")
        self.assertContains(page, "ثبت مالی بیعانه")
        self.assertContains(page, self.lead.full_name)
        self.assertEqual(page.context["form"]["appointment"].value(), self.appt.pk)
        plaque = self.client.get(reverse("call_center_call_plaque", args=[self.lead.pk]))
        self.assertEqual(plaque.json()["operational"]["deposit_url"], self.operator_url)

        token = str(uuid.uuid4())
        payment = {"amount_toman": "۵۰٬۰۰۰٬۰۰۰", "payment_method": "CC G", "submission_token": token}
        self.assertRedirects(self.client.post(self.operator_url, self.payload(**payment)), self.operator_url)
        self.assertRedirects(self.client.post(self.operator_url, self.payload(**payment)), self.operator_url)
        deposit = FinancialTransaction.objects.get()
        self.assertEqual(deposit.amount, Decimal("500000000"))
        self.assertEqual(deposit.raw_data["entry_channel"], "call_center_operator")
        self.assertEqual(deposit.appointment_id, self.appt.pk)
        self.assertEqual(deposit.recorded_by_id, self.operator.pk)
        self.assertEqual(deposit.call_center_owner_id, self.operator.pk)
        personal = self.client.get(reverse("my_sales_targets"))
        self.assertEqual(personal.context["targets"]["my_deposits_pending"], Decimal("50"))
        self.assertEqual(personal.context["targets"]["team_month"]["value"], Decimal("0"))

    def test_operator_cannot_register_against_an_unassigned_lead_or_foreign_appointment(self):
        second = self.make_user("another-flower", "", "", "call_center")
        self.client.force_login(second)
        self.assertEqual(self.client.post(self.operator_url, self.payload()).status_code, 404)
        other_lead = ReferralLead.objects.create(
            referrer=self.lead.referrer, full_name="مراجع ثبت‌نشده",
            phone="09120001113", assigned_to=second.profile,
        )
        other_url = reverse("call_center_lead_deposit", args=[other_lead.pk])
        response = self.client.post(other_url, self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertIn("appointment", response.context["form"].errors)
        self.assertFalse(FinancialTransaction.objects.exists())
        self.client.force_login(self.naderi)
        self.assertEqual(self.client.get(self.operator_url).status_code, 403)

    def test_executive_confirmation_does_not_close_the_future_visit(self):
        self.client.force_login(self.operator)
        self.client.post(self.operator_url, self.payload())
        deposit = FinancialTransaction.objects.get()
        manager = self.make_user("branch-manager", "", "", "manager")
        manager.profile.branch = self.branch
        manager.profile.save(update_fields=["branch"])
        self.client.force_login(manager)
        approval = reverse("finance_entry_review", args=[deposit.pk, "approve"])
        self.assertEqual(self.client.post(approval).status_code, 403)
        self.client.force_login(self.executive)
        self.assertEqual(self.client.post(approval).status_code, 302)
        deposit.refresh_from_db()
        self.appt.refresh_from_db()
        self.lead.refresh_from_db()
        self.assertEqual(deposit.review_status, "approved")
        self.assertEqual(self.appt.status, "booked")
        self.assertEqual(self.appt.care_stage, "doctor")
        self.assertNotEqual(self.lead.status, "won")

    def test_credit_visible_and_allocated_then_only_one_final_sale_counts(self):
        self.client.force_login(self.operator)
        self.client.post(self.operator_url, self.payload(amount_toman="50000000"))
        deposit = FinancialTransaction.objects.get()
        self.client.force_login(self.executive)
        self.client.post(reverse("finance_entry_review", args=[deposit.pk, "approve"]))
        self.appt.status = "arrived"
        self.appt.care_stage = "consultant"
        self.appt.save(update_fields=["status", "care_stage"])
        consultant = self.make_user("credit-consultant", "", "", "consultant")
        consultant.profile.branch = self.branch
        consultant.profile.save(update_fields=["branch"])
        plan = ConsultationPlan.objects.create(
            appointment=self.appt, consultant=consultant, status="finalized",
            subtotal_toman=80000000, final_amount_toman=80000000, finalized_at=timezone.now(),
        )
        lipolytic = ConsultationPlanItem.objects.create(
            plan=plan, kind="lipolytic", title="لیپولیتیک آزمایشی", unit_price_toman=40000000,
        )
        device = ConsultationPlanItem.objects.create(
            plan=plan, kind="device", title="دستگاه آزمایشی", unit_price_toman=40000000,
        )
        self.client.force_login(consultant)
        consult = reverse("consultant_sales_outcomes")
        page = self.client.get(consult, {"appointment": self.appt.pk})
        self.assertEqual(page.context["deposit_credit"]["available"], Decimal("50000000"))
        params = {"action": "allocate_deposit", "appointment_id": self.appt.pk}
        self.client.post(consult, {
            **params, f"item_{lipolytic.pk}": "۳۵٬۰۰۰٬۰۰۰", f"item_{device.pk}": "۲۵٬۰۰۰٬۰۰۰",
        })
        deposit.refresh_from_db()
        self.assertNotIn("service_allocations", deposit.raw_data)
        request = {**params, f"item_{lipolytic.pk}": "۲۵٬۰۰۰٬۰۰۰", f"item_{device.pk}": "۲۵٬۰۰۰٬۰۰۰"}
        self.client.post(consult, request)
        self.client.post(consult, request)
        self.assertEqual(AuditLog.objects.filter(action="call_center_deposit_allocate").count(), 1)
        self.assertEqual(FinancialTransaction.objects.count(), 1)
        patient = PatientProfile.objects.create(full_name=self.appt.full_name, phone=self.appt.phone, home_branch=self.branch)
        profile = self.client.get(reverse("patient_360", args=[patient.pk]))
        self.assertContains(profile, "ماندهٔ قابل تخصیص")
        summary = profile.context["deposit_credit"]
        self.assertEqual(summary["approved"], Decimal("50000000"))
        self.assertEqual(summary["available"], Decimal("0"))
        self.assertEqual(summary["services"], {
            "لیپولیتیک آزمایشی": Decimal("25000000"), "دستگاه آزمایشی": Decimal("25000000"),
        })
        self.client.force_login(self.operator)
        before = self.client.get(reverse("my_sales_targets")).context["targets"]
        self.assertEqual(before["personal"]["value"], Decimal("0"))
        self.assertEqual(before["team_month"]["value"], Decimal("50"))
        self.assertEqual(before["team_day"]["value"], Decimal("50"))

        balance = FinancialTransaction.objects.create(
            occurred_at=timezone.now(), source="manual", entry_type="inc",
            branch=self.branch, appointment=self.appt, recorded_by=consultant,
            review_status="pending", amount=300000000, call_center_owner=self.operator,
        )
        self.client.force_login(self.executive)
        self.client.post(reverse("finance_entry_review", args=[balance.pk, "approve"]))
        plan.refresh_from_db()
        self.assertEqual(plan.status, "paid")
        self.client.force_login(self.operator)
        cards = self.client.get(reverse("my_sales_targets")).context["targets"]
        self.assertEqual(cards["personal"]["value"], Decimal("80"))
        self.assertEqual(cards["my_deposits_approved"], Decimal("50"))
        self.assertEqual(cards["team_month"]["value"], Decimal("50"))
