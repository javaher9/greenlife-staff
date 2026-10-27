from datetime import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.models import Branch, EmployeeProfile, FinancialTransaction
from core.templatetags.finance_intelligence import _app_revenue_snapshot, finance_intelligence


class AfsariyehFinanceChannelTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="نیاوران")
        self.user = User.objects.create_user("finance-afsariyeh-admin")
        EmployeeProfile.objects.update_or_create(
            user=self.user, defaults={"role": "admin", "is_active": True},
        )
        self.today = timezone.localdate()
        now = timezone.now()
        self.deposit = FinancialTransaction.objects.create(
            source="manual", branch=self.branch,
            amount=Decimal("20000000"), entry_type="inc",
            review_status="approved", occurred_at=now,
            raw_data={"payment_kind": "call_center_deposit"},
        )
        self.normal = FinancialTransaction.objects.create(
            source="manual", branch=self.branch,
            amount=Decimal("30000000"), entry_type="inc",
            review_status="approved", occurred_at=now,
        )
        FinancialTransaction.objects.create(
            source="manual", branch=self.branch,
            amount=Decimal("10000000"), entry_type="inc",
            review_status="pending", occurred_at=now,
            raw_data={"payment_kind": "call_center_deposit"},
        )

    def report(self, **params):
        request = RequestFactory().get("/finance/", {"period": "today", **params})
        request.user = self.user
        return finance_intelligence({"request": request, "selected": self.today})

    def test_chart_shows_afsariyeh_as_separate_pink_channel_without_double_counting(self):
        snapshot = _app_revenue_snapshot(self.today)
        amounts = {item["name"]: item["total"] for item in snapshot["branches"]}
        self.assertEqual(amounts["افسریه"], Decimal("20000000"))
        self.assertEqual(amounts["نیاوران"], Decimal("30000000"))
        self.assertEqual(snapshot["grand_total"], Decimal("50000000"))
        self.assertEqual(snapshot["grand_total_display"], "5")
        colors = {item["name"]: item["color"] for item in snapshot["branches"]}
        self.assertEqual(colors["افسریه"], "#ec4899")
        today_row = next(row for row in snapshot["timeline"] if row["date"] == self.today.isoformat())
        self.assertEqual(today_row["values"]["افسریه"], Decimal("20000000"))
        self.assertEqual(today_row["values"]["نیاوران"], Decimal("30000000"))

    def test_bar_chart_and_matrix_reconcile_to_single_approved_total(self):
        report = self.report()
        self.assertEqual(report["total"], Decimal("50000000"))
        bars = {item["label"]: item["total"] for item in report["branch_rows"]}
        self.assertEqual(bars["افسریه"], Decimal("20000000"))
        self.assertEqual(bars["نیاوران"], Decimal("30000000"))
        self.assertEqual(sum(bars.values()), report["total"])
        matrix = {item["branch"].name: item["total"] for item in report["matrix_total_cells"]}
        self.assertEqual(matrix["افسریه"], Decimal("20000000"))
        self.assertEqual(matrix["نیاوران"], Decimal("30000000"))
        self.assertEqual(report["matrix_reconciled_total"], report["total"])

    def test_selected_afsariyeh_filters_only_its_deposits(self):
        report = self.report(branch="afsariyeh")
        self.assertTrue(report["afsariyeh_only"])
        self.assertEqual(report["total"], Decimal("20000000"))
        self.assertEqual(report["pending_total"], Decimal("10000000"))
        self.assertEqual(report["external_revenue"]["grand_total"], Decimal("20000000"))
        self.assertEqual({row["label"] for row in report["branch_rows"]}, {"افسریه"})
