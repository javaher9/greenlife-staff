"""Four named units remain visible on the finance card even without receipts."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.models import Branch, EmployeeProfile, FinancialTransaction
from core.templatetags.finance_intelligence import finance_intelligence


class FinanceFourBranchCardTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("finance-branch-tiles-admin", password="test")
        EmployeeProfile.objects.update_or_create(
            user=self.admin, defaults={"role": "admin", "is_active": True},
        )
        self.niyavaran = Branch.objects.create(name="نیاوران")
        self.ponak = Branch.objects.create(name="پونک")
        self.other = Branch.objects.create(name="ارومیه")

    def receipt(self, amount, branch, *, status="approved", deposit=False):
        return FinancialTransaction.objects.create(
            source="manual", branch=branch, occurred_at=timezone.now(),
            entry_type="inc", review_status=status, amount=Decimal(str(amount)),
            payment_method="Pos S",
            raw_data={"payment_kind": "call_center_deposit"} if deposit else {},
        )

    def report(self, **params):
        request=RequestFactory().get("/finance/", {"period":"today", **params})
        request.user=self.admin
        return finance_intelligence({"request":request, "selected":timezone.localdate()})

    def test_empty_report_still_has_four_named_zero_slots(self):
        report=self.report()
        rows=report["branch_chart_rows"]
        self.assertEqual([r["label"] for r in rows],
                         ["نیاوران","پونک","اصفهان","کال‌سنتر"])
        self.assertTrue(all(r["total"] == 0 and r["height"] == 0 for r in rows))
        self.client.force_login(self.admin)
        page=self.client.get("/finance/")
        self.assertEqual(page.status_code, 200)
        html=page.content.decode("utf-8").split(
            'aria-label="نمودار چهار واحد ثابت درآمد تأییدشده"',1
        )[1].split("</section>",1)[0]
        self.assertEqual(html.count('class="fin44-revenue-col is-zero"'),4)
        self.assertNotIn('class="fin44-revenue-bar"',html)
        for label in ("نیاوران","پونک","اصفهان","کال‌سنتر"):
            self.assertIn(label,html)

    def test_approved_deposits_appear_only_in_call_center_card_slot(self):
        self.receipt("100000000", self.niyavaran)
        self.receipt("20000000", self.niyavaran, deposit=True)
        self.receipt("60000000", self.ponak)
        self.receipt("90000000", self.ponak, status="pending")
        report=self.report()
        rows={r["label"]:r for r in report["branch_chart_rows"]}
        self.assertEqual(rows["نیاوران"]["total"],Decimal("100000000"))
        self.assertEqual(rows["پونک"]["total"],Decimal("60000000"))
        self.assertEqual(rows["کال‌سنتر"]["total"],Decimal("20000000"))
        self.assertEqual(rows["اصفهان"]["total"],Decimal("0"))
        self.assertEqual(report["total"],Decimal("180000000"))
        self.assertEqual(sum(r["total"] for r in rows.values()),report["total"])
        self.assertEqual(rows["نیاوران"]["height"],100)
        self.assertEqual(rows["اصفهان"]["height"],0)

    def test_old_closed_branch_is_not_hidden_from_reconciliation(self):
        self.receipt("60000000",self.other)
        report=self.report()
        self.assertEqual(report["branch_chart_other_total"],Decimal("60000000"))
        self.assertEqual(sum(r["total"] for r in report["branch_chart_rows"]),0)
        self.assertEqual(report["total"],Decimal("60000000"))
        self.client.force_login(self.admin)
        page=self.client.get("/finance/")
        self.assertContains(page,"درآمد سایر شعب در جمع کل لحاظ شده است")

    def test_branch_filter_preserves_all_four_positions(self):
        self.receipt("70000000",self.niyavaran)
        report=self.report(branch=str(self.ponak.pk))
        self.assertEqual(report["total"],0)
        self.assertEqual([r["label"] for r in report["branch_chart_rows"]],
                         ["نیاوران","پونک","اصفهان","کال‌سنتر"])
        self.assertTrue(all(r["total"]==0 for r in report["branch_chart_rows"]))
