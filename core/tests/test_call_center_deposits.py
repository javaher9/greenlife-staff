import uuid
from datetime import time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import (
    AuditLog, Branch, EmployeeProfile, FinancialTransaction,
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
            phone="09120005555", first_appointment_by=self.operator,
        )
        self.appt = VisitAppointment.objects.create(
            lead=self.lead, branch=self.branch, full_name=self.lead.full_name,
            phone=self.lead.phone, appointment_date=timezone.localdate(),
            appointment_time=time(10, 0), source="call_center",
            created_by=self.operator, status="booked",
        )
        self.url = "/call-center/deposits/new/"

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
