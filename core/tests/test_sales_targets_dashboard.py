"""Regression tests for isolated executive sales-target dashboard."""
from datetime import datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Branch, EmployeeProfile, FinancialTransaction, SalesTargetBand
from core.jalali import gregorian_to_jalali


class SalesTargetsDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser(
            username="targets_admin", email="targets@example.test", password="test-secret"
        )
        cls.staff = User.objects.create_user(username="targets_staff", password="test-secret")
        cls.consultant = User.objects.create_user(username="targets_consultant", password="test-secret")
        cls.flower = User.objects.create_user(
            username="targets_flower", first_name="محمد", last_name="صالحی", password="test-secret"
        )
        cls.branch = Branch.objects.create(name="نیاوران تست", is_active=True)
        cls.closed = Branch.objects.create(name="ارومیه", is_active=False)
        EmployeeProfile.objects.update_or_create(user=cls.staff, defaults={"role":"employee","branch":cls.branch})
        EmployeeProfile.objects.update_or_create(user=cls.consultant, defaults={"role":"consultant","branch":cls.branch})
        EmployeeProfile.objects.update_or_create(user=cls.flower, defaults={"role":"call_center","branch":cls.branch})

    def setUp(self):
        self.client.force_login(self.admin)
        self.year, self.month, _ = gregorian_to_jalali(
            timezone.localdate().year, timezone.localdate().month, timezone.localdate().day
        )
        self.url = reverse("sales_targets_dashboard")

    def _transaction(self, amount, *, description="", origin="", owner=None, recorded=None, branch=None):
        return FinancialTransaction.objects.create(
            source="manual", entry_type="inc", review_status="approved",
            occurred_at=timezone.now(), amount=Decimal(amount),
            branch=branch or self.branch, sale_origin=origin, description=description,
            call_center_owner=owner, recorded_by=recorded,
        )

    def test_renders_without_any_configured_targets_and_excludes_closed_branch(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "کال‌سنتر")
        self.assertContains(response, "نیاوران تست")
        self.assertNotContains(response, ">ارومیه<")
        self.assertContains(response, "تارگت تنظیم نشده")

    def test_valid_and_invalid_thresholds_and_monthly_isolation(self):
        values = dict(year=self.year, month=self.month, subject=f"branch:{self.branch.pk}",
                      heavy_limit="100", sales_floor="200", target_one="300", target_two="450")
        self.assertEqual(self.client.post(self.url, values).status_code, 302)
        target = SalesTargetBand.objects.get(key=f"{self.year}-{self.month:02d}:branch:{self.branch.pk}")
        self.assertEqual(target.target_two, Decimal("450"))
        self.assertEqual(SalesTargetBand.objects.count(), 1)
        self.client.post(self.url, {**values, "sales_floor":"500"})
        self.assertEqual(SalesTargetBand.objects.count(), 1)
        self.assertEqual(SalesTargetBand.objects.get(pk=target.pk).target_two, Decimal("450"))
        self.client.post(self.url, {**values, "target_two":"600"})
        self.assertEqual(SalesTargetBand.objects.get(pk=target.pk).target_two, Decimal("600"))
        self.assertEqual(SalesTargetBand.objects.count(), 1)

    def test_call_center_deposit_only_counts_explicit_deposit_transactions(self):
        self._transaction("40000000", description="بیعانه", origin="afsariyeh", owner=self.flower)
        self._transaction("90000000", description="پکیج کامل", origin="afsariyeh", owner=self.flower)
        self._transaction("50000000", description="بیعانه", origin="branch_walk_in", recorded=self.consultant)
        # A cancelled or pending receipt must never contribute to target totals.
        FinancialTransaction.objects.create(
            source="manual", entry_type="inc", review_status="pending",
            occurred_at=timezone.now(), amount=Decimal("70000000"),
            branch=self.branch, sale_origin="afsariyeh", description="بیعانه",
        )
        res = self.client.get(self.url)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["branches"][-1]["value"], Decimal("4.00"))
        self.assertEqual(res.context["deposit_count"], 1)
        flower_row = res.context["flower_cards"][0]
        self.assertEqual(flower_row["value"], Decimal("13.00"))
        self.assertEqual(res.context["overall"]["value"], Decimal("18.00"))

    def test_non_management_user_forbidden(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        response = self.client.post(self.url, {"subject":"overall","target_one":"1"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(SalesTargetBand.objects.count(), 0)
