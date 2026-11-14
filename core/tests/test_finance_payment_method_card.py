"""Payment channel card uses one source of truth: approved and filtered income."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.models import Branch, EmployeeProfile, FinancialTransaction
from core.templatetags.finance_intelligence import finance_intelligence


class FinancePaymentMethodCardTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_user("payment-card-admin")
        EmployeeProfile.objects.update_or_create(
            user=self.admin,defaults={"role":"admin","is_active":True},
        )
        self.branch=Branch.objects.create(name="نیاوران")
        self.other_branch=Branch.objects.create(name="پونک")

    def income(self, amount, method, *, status="approved", branch=None):
        return FinancialTransaction.objects.create(
            source="manual",branch=branch or self.branch,
            occurred_at=timezone.now(),amount=Decimal(str(amount)),
            entry_type="inc",review_status=status,
            payment_method=method,sale_reason="device_package",
        )

    def report(self, **filters):
        req=RequestFactory().get("/finance/",{"period":"today",**filters})
        req.user=self.admin
        return finance_intelligence({"request":req,"selected":timezone.localdate()})

    def test_payment_channels_total_exactly_matches_approved_revenue(self):
        self.income("100000000","Pos H")
        self.income("200000000","Pos S")
        self.income("50000000","CC S")
        self.income("30000000","",branch=self.other_branch)
        self.income("40000000","FUTURE-POS-NEW")
        self.income("900000000","Pos H",status="pending")
        result=self.report()
        rows={r["code"]:r for r in result["payment_method_rows"]}
        self.assertEqual(result["total"],Decimal("420000000"))
        self.assertEqual(sum((r["total"] for r in rows.values()),Decimal("0")),result["total"])
        self.assertEqual(rows["Pos H"]["label"],"POS-H")
        self.assertEqual(rows["Pos S"]["label"],"POS-S")
        self.assertEqual(rows["CC S"]["label"],"CC-S")
        self.assertEqual(rows[""]["label"],"روش نامشخص")
        self.assertEqual(rows["FUTURE-POS-NEW"]["label"],"FUTURE-POS-NEW")
        self.assertEqual(rows["Pos S"]["pct"],round(200000000*100/420000000,1))
        self.assertEqual(rows["Pos S"]["relative"],100)

    def test_payment_channels_respect_branch_and_service_filters(self):
        self.income("100000000","Pos H",branch=self.branch)
        self.income("250000000","Pos S",branch=self.other_branch)
        selected=self.report(branch=str(self.branch.pk),service="device_package")
        self.assertEqual(selected["total"],Decimal("100000000"))
        self.assertEqual(len(selected["payment_method_rows"]),1)
        self.assertEqual(selected["payment_method_rows"][0]["label"],"POS-H")

    def test_new_card_is_visible_and_donut_legend_is_below(self):
        self.income("150000000","Pos H")
        self.client.force_login(self.admin)
        response=self.client.get("/finance/")
        self.assertEqual(response.status_code,200)
        self.assertContains(response,"پول از کجا آمده؟")
        self.assertContains(response,"POS-H")
        self.assertContains(response,"fin44-payment-list")
        self.assertContains(response,"fin44-grid3")
