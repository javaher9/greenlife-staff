"""Focused regression tests: historical financial comparison is read-only and scoped."""
from datetime import datetime, time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.jalali import jalali_to_gregorian
from core.models import Branch, Country, EmployeeProfile, FinancialTransaction


class FinanceMonthComparisonTests(TestCase):
    def setUp(self):
        self.iran, _ = Country.objects.get_or_create(
            code="IR", defaults={"name_english": "Iran", "name_local": "ایران", "currency_code": "IRR"}
        )
        self.turkey, _ = Country.objects.get_or_create(
            code="TR", defaults={"name_english": "Turkey", "name_local": "ترکیه", "currency_code": "TRY"}
        )
        self.nia = Branch.objects.create(name="نیاوران", country=self.iran)
        self.ponak = Branch.objects.create(name="پونک", country=self.iran)
        self.istanbul, _ = Branch.objects.get_or_create(name="استانبول", defaults={"country": self.turkey})
        self.owner = User.objects.create_user("finance-comparison-admin", password="safe-test")
        EmployeeProfile.objects.create(user=self.owner, role="admin")
        self.manager = User.objects.create_user("finance-comparison-manager", password="safe-test")
        EmployeeProfile.objects.create(user=self.manager, role="manager", branch=self.nia)
        self.staff = User.objects.create_user("finance-comparison-staff", password="safe-test")
        EmployeeProfile.objects.create(user=self.staff, role="employee", branch=self.ponak)
        self.path = "/finance/compare/?a=1405/07&b=1405/08"

    def receipt(self, month, day, amount, method, branch=None, status="approved", entry="inc", **extras):
        occurred = datetime(*jalali_to_gregorian(1405, month, day))
        timestamp = timezone.make_aware(datetime.combine(occurred.date(), time(14, 0)))
        return FinancialTransaction.objects.create(
            source="manual", branch=branch or self.nia,
            occurred_at=timestamp, amount=Decimal(str(amount)),
            review_status=status, entry_type=entry,
            payment_method=method, **extras,
        )

    def test_approved_income_and_aliases_reconcile_in_both_months(self):
        self.receipt(7, 10, 100000000, "Pos S")
        self.receipt(7, 10, 200000000, "Pos H")
        self.receipt(7, 21, 50000000, "CC G", branch=self.ponak)
        self.receipt(7, 15, 900000000, "POS-S", status="pending")
        self.receipt(8, 12, 150000000, "POS-S")
        self.receipt(8, 13, 300000000, "POS H", branch=self.ponak)
        self.receipt(8, 13, 10000000, "CC-G")
        self.receipt(8, 13, 20000000, "CCG", branch=self.ponak)
        self.receipt(8, 13, 800000000, "POS-S", entry="exp")

        self.client.force_login(self.owner)
        before = FinancialTransaction.objects.count()
        result = self.client.get(self.path)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.context["month_a"]["total_m"], Decimal("35.00"))
        self.assertEqual(result.context["month_b"]["total_m"], Decimal("48.00"))
        self.assertEqual(result.context["delta_m"], Decimal("13.00"))
        self.assertEqual(result.context["month_a"]["count"], 3)
        self.assertEqual(result.context["month_b"]["count"], 4)
        self.assertEqual(result.context["month_a"]["pending_count"], 1)
        self.assertEqual(result.context["month_b"]["pending_count"], 0)
        payment = {row["name"]: row for row in result.context["payments"]}
        self.assertEqual(payment["POS-S"]["a"], Decimal("10.00"))
        self.assertEqual(payment["POS-S"]["b"], Decimal("15.00"))
        self.assertEqual(payment["POS-H"]["a"], Decimal("20.00"))
        self.assertEqual(payment["POS-H"]["b"], Decimal("30.00"))
        self.assertEqual(payment["CC-G"]["a"], Decimal("5.00"))
        self.assertEqual(payment["CC-G"]["b"], Decimal("3.00"))
        self.assertEqual(sum(row["a"] for row in payment.values()), Decimal("35.00"))
        self.assertEqual(sum(row["b"] for row in payment.values()), Decimal("48.00"))
        self.assertEqual(FinancialTransaction.objects.count(), before)

    def test_branch_comparison_and_deposit_attribution_do_not_duplicate(self):
        self.receipt(7, 10, 100000000, "POS-S", branch=self.nia)
        self.receipt(
            7, 11, 25000000, "CC S", branch=self.nia,
            raw_data={"payment_kind": "call_center_deposit"},
        )
        self.receipt(8, 12, 60000000, "POS-H", branch=self.ponak)
        self.client.force_login(self.owner)
        result = self.client.get(self.path)
        branches = {row["name"]: row for row in result.context["branch_rows"]}
        self.assertEqual(branches["نیاوران"]["a"], Decimal("10.00"))
        self.assertEqual(branches["افسریه"]["a"], Decimal("2.50"))
        self.assertEqual(branches["پونک"]["b"], Decimal("6.00"))
        self.assertEqual(sum(row["a"] for row in branches.values()), result.context["month_a"]["total_m"])
        self.assertEqual(sum(row["b"] for row in branches.values()), result.context["month_b"]["total_m"])

    def test_day_series_is_not_cumulative_and_contains_month_lengths(self):
        self.receipt(7, 1, 10000000, "Pos S")
        self.receipt(7, 1, 20000000, "Pos S")
        self.receipt(7, 3, 5000000, "Pos H")
        self.receipt(8, 2, 70000000, "Pos S")
        self.client.force_login(self.owner)
        res = self.client.get(self.path)
        chart = res.context["chart_rows"]
        self.assertEqual(chart[0]["a"], 3.0)
        self.assertEqual(chart[0]["a_count"], 2)
        self.assertEqual(chart[1]["a"], 0.0)
        self.assertEqual(chart[2]["a"], 0.5)
        self.assertEqual(chart[1]["b"], 7.0)
        self.assertEqual(sum(row["a"] or 0 for row in chart), 3.5)
        self.assertEqual(sum(row["b"] or 0 for row in chart), 7.0)
        self.assertTrue(len(chart) in (30, 31))
        self.assertContains(res, 'id="fmc-chart-data"')

    def test_branch_manager_cannot_request_other_branch_or_iran_total(self):
        self.receipt(7, 10, 100000000, "POS-S", branch=self.nia)
        self.receipt(7, 10, 700000000, "POS-H", branch=self.ponak)
        self.client.force_login(self.manager)
        res = self.client.get(self.path + "&branch=" + str(self.ponak.pk))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["month_a"]["total_m"], Decimal("10.00"))
        self.assertEqual({row["name"] for row in res.context["branch_rows"]}, {"نیاوران"})

    def test_nonfinance_user_does_not_receive_finance_data(self):
        self.receipt(7, 1, 20000000, "Pos H")
        self.client.force_login(self.staff)
        result = self.client.get(self.path)
        self.assertEqual(result.status_code, 302)
        self.assertNotIn("fmc-chart-data", result.content.decode("utf-8"))
        self.client.logout()
        login_redirect = self.client.get(self.path)
        self.assertEqual(login_redirect.status_code, 302)

    def test_foreign_branch_amounts_are_not_mixed_into_rial_totals(self):
        self.receipt(7, 1, 100000000, "POS-S", branch=self.nia)
        self.receipt(7, 1, 1000000000, "POS-H", branch=self.istanbul)
        self.client.force_login(self.owner)
        response = self.client.get(self.path)
        self.assertEqual(response.context["month_a"]["total_m"], Decimal("10.00"))
        self.assertNotIn("استانبول", {row["name"] for row in response.context["branch_rows"]})

    def test_empty_period_shows_pinned_channels_not_fake_income(self):
        self.client.force_login(self.owner)
        res = self.client.get(self.path)
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.context["month_a"]["total"], Decimal("0"))
        self.assertEqual(res.context["month_b"]["total"], Decimal("0"))
        pay = {row["name"]: row for row in res.context["payments"]}
        self.assertTrue({"POS-S", "POS-H", "CC-S", "CC-G"}.issubset(pay))
        self.assertEqual(sum(row["a"] for row in pay.values()), 0)
        self.assertEqual(sum(row["b"] for row in pay.values()), 0)

    def test_invalid_month_falls_back_safely(self):
        self.client.force_login(self.owner)
        res = self.client.get("/finance/compare/?a=%%%%&b=1405/13")
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.context["invalid_month"])
        self.assertContains(res, "ماه انتخاب‌شده معتبر نبود")
