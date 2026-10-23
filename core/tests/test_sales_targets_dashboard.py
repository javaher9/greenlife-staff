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

    def test_compact_branch_only_layout_and_target_free_color_legend(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "تارگت فروش مراکز و کال‌سنتر")
        self.assertContains(response, "مشاورین نیاوران تست")
        self.assertNotContains(response, "◉ مشاورین فروش شعب")
        self.assertContains(response, "◉ فروش گل‌های کال‌سنتر")
        self.assertContains(response, "هنوز هیچ کف فروش یا تارگتی")
        self.assertContains(response, 'const colors=["#fc4768"')
        self.assertFalse(response.context["has_sales"])
        self.assertTrue(response.context["branches"][0]["people"])

    def test_sales_trend_empty_state_changes_when_real_sale_exists(self):
        empty = self.client.get(self.url)
        self.assertContains(empty, "فروش تأییدشده‌ای در منبع این نمودار ثبت نشده است")
        self._transaction("100000000", recorded=self.consultant)
        paid = self.client.get(self.url)
        self.assertTrue(paid.context["has_sales"])
        self.assertNotContains(paid, "فروش تأییدشده‌ای در منبع این نمودار ثبت نشده است")

    def test_single_floor_policy_edit_and_dynamic_band_recalculation(self):
        floor = dict(year=self.year, month=self.month, action="set_floor",
                     subject=f"branch:{self.branch.pk}", sales_floor="200")
        self.assertEqual(self.client.post(self.url, floor).status_code, 302)
        item = SalesTargetBand.objects.get()
        self.assertEqual(item.sales_floor, Decimal("200"))
        response = self.client.get(self.url)
        self.assertEqual(response.context["branches"][0]["plan"].target_one, Decimal("260"))
        self.assertEqual(response.context["branches"][0]["plan"].target_two, Decimal("320"))
        percent = dict(year=self.year, month=self.month, action="set_policy",
                       heavy_percent="55", target_one_percent="145", target_two_percent="190")
        self.assertEqual(self.client.post(self.url, percent).status_code, 302)
        response = self.client.get(self.url)
        plan = response.context["branches"][0]["plan"]
        self.assertEqual(plan.heavy_limit, Decimal("110"))
        self.assertEqual(plan.sales_floor, Decimal("200"))
        self.assertEqual(plan.target_one, Decimal("290"))
        self.assertEqual(plan.target_two, Decimal("380"))
        # Policy is global; old saved target values must not override it.
        self.assertEqual(SalesTargetBand.objects.get().target_one, Decimal("260"))
        self.client.post(self.url, {**percent, "target_one_percent":"200"})
        self.assertEqual(self.client.get(self.url).context["target_policy"].target_one_percent, Decimal("145"))
        self.assertEqual(SalesTargetBand.objects.count(), 1)

    def test_personal_sales_targets_are_read_only_and_not_shared(self):
        self.client.post(self.url, {
            "year":self.year, "month":self.month, "action":"set_floor",
            "subject":f"flower:{self.flower.pk}", "sales_floor":"300",
        })
        self._transaction("40000000", description="بیعانه", origin="afsariyeh", owner=self.flower)
        self._transaction("100000000", recorded=self.consultant)
        personal_url = reverse("my_sales_targets")
        self.client.force_login(self.flower)
        view = self.client.get(personal_url)
        self.assertEqual(view.status_code, 200)
        self.assertContains(view, "تارگت امروز")
        self.assertEqual(view.context["monthly"], Decimal("4.00"))
        self.assertEqual(view.context["plan"].sales_floor, Decimal("300"))
        self.assertContains(view, "هیچ جریمه‌ای")
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.consultant)
        other = self.client.get(personal_url)
        self.assertEqual(other.status_code, 200)
        self.assertIsNone(other.context["plan"])
        self.assertEqual(other.context["monthly"], Decimal("10.00"))
        self.assertEqual(self.client.post(personal_url, {"sales_floor":"1"}).status_code, 200)
        self.assertEqual(SalesTargetBand.objects.count(), 1)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(personal_url).status_code, 403)

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
