from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, Branch, EmployeeProfile, FinancialTransaction, PatientProfile


@override_settings(EXECUTIVE_USERNAMES=("deposit-reviewer",))
class FinanceAmountCorrectionTests(TestCase):
    def test_correction_is_audited_and_keeps_unassigned_deposit_on_the_patient_account(self):
        reviewer = User.objects.create_user("deposit-reviewer")
        EmployeeProfile.objects.update_or_create(user=reviewer, defaults={"role": "admin"})
        branch = Branch.objects.create(name="مرکز نمونه")
        patient = PatientProfile.objects.create(full_name="مراجع نمونه", phone="09121234567")
        payment = FinancialTransaction.objects.create(
            source="manual", review_status="pending", occurred_at=timezone.now(), amount=20000000,
            patient_ref=f"patient:{patient.pk}", person_name=patient.full_name,
            payment_method="LINK", tracking_number="TEST-REVIEW-1", sale_origin="afsariyeh",
            raw_data={"payment_kind": "call_center_deposit", "country_code": "IR"},
        )
        self.client.force_login(reviewer)
        url = reverse("finance_entry_review", args=[payment.pk, "correction"])
        page = self.client.post(url)
        self.assertContains(page, 'name="corrected_amount"')
        self.assertContains(page, "در انتظار مراجعه")
        self.assertNotContains(page, 'name="branch_id"')
        self.assertRedirects(self.client.post(url, {
            "corrected_amount": "3", "entry_type": "inc", "payment_method": "LINK",
            "tracking_number": payment.tracking_number, "person_name": patient.full_name,
            "branch_id": branch.pk, "sale_origin": "branch_walk_in",
        }), reverse("finance_dashboard"), fetch_redirect_response=False)
        payment.refresh_from_db()
        self.assertEqual(payment.amount, Decimal("30000000"))
        self.assertEqual(payment.review_status, "approved")
        self.assertIsNone(payment.branch_id)
        self.assertEqual(payment.patient_ref, f"patient:{patient.pk}")
        self.assertEqual(payment.sale_origin, "afsariyeh")
        audit = AuditLog.objects.get(action="finance_transaction_correction", object_id=str(payment.pk))
        self.assertEqual(Decimal(audit.metadata["changes"]["amount"]["before"]), Decimal("20000000"))
        self.assertEqual(Decimal(audit.metadata["changes"]["amount"]["after"]), Decimal("30000000"))
