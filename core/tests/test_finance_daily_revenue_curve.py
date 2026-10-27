from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Branch, FinancialTransaction
from core.templatetags.finance_intelligence import (
    _app_revenue_snapshot, _million_toman_display,
)


class DailyRevenueChartTests(TestCase):
    def test_million_toman_conversion_from_rial(self):
        self.assertEqual(_million_toman_display(Decimal("10000000")), "1")
        self.assertEqual(_million_toman_display(Decimal("25000000")), "2.5")

    def test_days_are_independent_and_month_totals_reconcile(self):
        day = timezone.localdate()
        # Freeze within a fixed Jalali month with three distinct dates.
        day = datetime(2026, 10, 27).date()
        first = day - timedelta(days=2)
        second = day - timedelta(days=1)
        branch = Branch.objects.create(name="نیاوران")
        for when, amount in (
            (first, "10000000"), (second, "20000000"),
            (second, "5000000"), (day, "5000000"),
        ):
            FinancialTransaction.objects.create(
                source="manual", review_status="approved", entry_type="inc",
                branch=branch, amount=Decimal(amount),
                occurred_at=timezone.make_aware(datetime.combine(when, datetime.min.time())),
            )
        FinancialTransaction.objects.create(
            source="manual", review_status="pending", entry_type="inc",
            branch=branch, amount=Decimal("90000000"),
            occurred_at=timezone.make_aware(datetime.combine(day, datetime.min.time())),
        )
        report = _app_revenue_snapshot(day)
        self.assertEqual(report["grand_total"], Decimal("40000000"))
        self.assertEqual(report["grand_total_display"], "4")
        self.assertEqual(report["branches"][0]["total_display"], "4")
        days = {row["date"]: row["values"].get("نیاوران", 0) for row in report["timeline"]}
        self.assertEqual(days[first.isoformat()], Decimal("10000000"))
        self.assertEqual(days[second.isoformat()], Decimal("25000000"))
        self.assertEqual(days[day.isoformat()], Decimal("5000000"))
        self.assertEqual(sum(days.values()), report["grand_total"])
