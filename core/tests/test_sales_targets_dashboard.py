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
        self.assertContains(response, "◉ مجموع فروش گل‌های کال‌سنتر")
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

    def test_bulk_save_replaces_8000_with_7000_and_updates_sliders(self):
        base={"year":self.year,"month":self.month,"action":"set_floor","subject":"overall","sales_floor":"8000"}
        self.client.post(self.url,base)
        page=self.client.get(self.url+"?edit=1")
        subjects=[row["key"] for row in page.context["edit_rows"]]
        form={"year":str(self.year),"month":str(self.month),"action":"save_all",
              "heavy_percent":"65","target_one_percent":"135","target_two_percent":"175",
              "subject":subjects,"floor_overall":"7000"}
        res=self.client.post(self.url,form)
        self.assertEqual(res.status_code,302)
        page=self.client.get(self.url+"?edit=1")
        self.assertEqual(page.context["overall"]["plan"].sales_floor,Decimal("7000"))
        self.assertEqual(page.context["overall"]["plan"].heavy_limit,Decimal("4550"))
        self.assertEqual(page.context["overall"]["plan"].target_one,Decimal("9450"))
        self.assertEqual(page.context["overall"]["plan"].target_two,Decimal("12250"))
        self.assertContains(page,'name="action" value="save_all"')
        self.assertContains(page,'type="range"')
        self.assertContains(page,'ذخیره همه تغییرات')
        self.assertEqual(SalesTargetBand.objects.get(key=f"{self.year}-{self.month:02d}:overall").sales_floor,Decimal("7000"))

    def test_center_and_flower_photos_but_no_aggregate_callcenter_photo(self):
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, 'b.key != "call_center" and b.people', count=0)
        template = page.templates[-1]
        from pathlib import Path
        from django.conf import settings
        source = (Path(settings.BASE_DIR) / "core/templates/core/sales_targets_dashboard.html").read_text()
        self.assertIn('{% if b.key != "call_center" and b.people %}', source)
        self.assertIn('<div class="st-person-header"><div class="st-person-name"', source)
        self.assertIn('alt="{{ p.label }}"', source)

    def test_consultant_settings_are_not_duplicated_and_personal_uses_branch_floor(self):
        page = self.client.get(self.url+"?edit=1")
        keys = [x["key"] for x in page.context["edit_rows"]]
        self.assertNotIn(f"consultant:{self.consultant.pk}", keys)
        self.assertIn(f"branch:{self.branch.pk}", keys)
        self.client.post(self.url, {
            "year": self.year, "month": self.month, "action": "set_floor",
            "subject": f"branch:{self.branch.pk}", "sales_floor": "4500",
        })
        self.client.force_login(self.consultant)
        own = self.client.get(reverse("my_sales_targets"))
        self.assertEqual(own.status_code, 200)
        self.assertEqual(own.context["plan"].sales_floor, Decimal("4500"))

    def test_bulk_call_center_and_flower_goals_are_saved(self):
        response = self.client.get(self.url+"?edit=1")
        subjects = [row["key"] for row in response.context["edit_rows"]]
        payload = {"year":self.year,"month":self.month,"action":"save_all",
                   "heavy_percent":"70","target_one_percent":"130","target_two_percent":"160",
                   "subject":subjects,"floor_call_center":"400",
                   f"floor_flower:{self.flower.pk}":"150",
                   f"floor_flower_deposit:{self.flower.pk}":"35"}
        response = self.client.post(self.url,payload)
        self.assertEqual(response.status_code,302)
        response = self.client.get(self.url+"?edit=1")
        self.assertEqual(response.context["branches"][-1]["plan"].sales_floor,Decimal("400"))
        self.assertEqual(next(row for row in response.context["flower_cards"] if row["key"] == f"flower:{self.flower.pk}")["plan"].sales_floor,Decimal("150"))
        payload["floor_call_center"] = "350"
        payload[f"floor_flower:{self.flower.pk}"] = "125"
        response = self.client.post(self.url,payload,follow=True)
        feedback = [str(m) for m in list(response.context["messages"])]
        self.assertEqual(SalesTargetBand.objects.get(key=f"{self.year}-{self.month:02d}:call_center").sales_floor,Decimal("350"), feedback)
        self.assertEqual(SalesTargetBand.objects.get(key=f"{self.year}-{self.month:02d}:flower:{self.flower.pk}").sales_floor,Decimal("125"))
        deposit_plan = SalesTargetBand.objects.get(key=f"{self.year}-{self.month:02d}:flower_deposit:{self.flower.pk}")
        self.assertEqual(deposit_plan.employee, self.flower)
        self.assertEqual(deposit_plan.sales_floor, Decimal("35"))

    def test_bulk_callcenter_edit_survives_changed_staff_roster(self):
        # An extra active employee can appear after a form was opened.
        previous = [row["key"] for row in self.client.get(self.url).context["edit_rows"]]
        extra = get_user_model().objects.create_user(username="new_callcenter",password="test-secret")
        EmployeeProfile.objects.update_or_create(user=extra,defaults={"role":"call_center","branch":self.branch})
        payload={"year":self.year,"month":self.month,"action":"save_all","subject":previous,
                 "floor_call_center":"800","heavy_percent":"70",
                 "target_one_percent":"130","target_two_percent":"160"}
        res=self.client.post(self.url,payload)
        self.assertEqual(res.status_code,302)
        self.assertEqual(SalesTargetBand.objects.get(key=f"{self.year}-{self.month:02d}:call_center").sales_floor,Decimal("800"))

    def test_invalid_bulk_percent_rolls_back_floor_and_policy(self):
        self.client.post(self.url,{"year":self.year,"month":self.month,
              "action":"set_floor","subject":"overall","sales_floor":"8000"})
        subjects=[row["key"] for row in self.client.get(self.url).context["edit_rows"]]
        res=self.client.post(self.url,{"year":self.year,"month":self.month,"action":"save_all",
             "subject":subjects,"floor_overall":"7000","heavy_percent":"95",
             "target_one_percent":"190","target_two_percent":"150"})
        self.assertEqual(res.status_code,302)
        page=self.client.get(self.url)
        self.assertEqual(page.context["overall"]["plan"].sales_floor,Decimal("8000"))
        self.assertEqual(page.context["target_policy"].target_one_percent,Decimal("130"))

    def test_personal_sales_targets_are_read_only_and_not_shared(self):
        self.client.post(self.url, {
            "year":self.year, "month":self.month, "action":"set_floor",
            "subject":f"flower:{self.flower.pk}", "sales_floor":"300",
        })
        self.client.post(self.url, {
            "year": self.year, "month": self.month, "action": "set_floor",
            "subject": f"flower_deposit:{self.flower.pk}", "sales_floor": "12",
        })
        self._transaction("40000000", description="بیعانه", origin="afsariyeh", owner=self.flower)
        self._transaction("100000000", recorded=self.consultant)
        personal_url = reverse("my_sales_targets")
        self.client.force_login(self.flower)
        view = self.client.get(personal_url)
        self.assertEqual(view.status_code, 200)
        self.assertContains(view, "تارگت کل کال‌سنتر")
        self.assertContains(view, "بیعانه‌های من")
        self.assertContains(view, "مجموع فروش من")
        self.assertContains(view, "هر دو تارگت ماهانه‌اند")
        self.assertContains(view, "data-status-only", count=2)
        self.assertNotContains(view, 'class="cc-target-amount"')
        self.assertNotContains(view, '<th>مبلغ (تومان)</th>')
        self.assertEqual(view.context["targets"]["personal_deposit"]["value"], Decimal("4.00"))
        self.assertEqual(view.context["targets"]["personal_deposit"]["plan"].sales_floor, Decimal("12"))
        self.assertEqual(view.context["targets"]["personal"]["value"], Decimal("4.00"))
        self.assertEqual(view.context["targets"]["personal"]["plan"].sales_floor, Decimal("300"))
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.consultant)
        other = self.client.get(personal_url)
        self.assertEqual(other.status_code, 200)
        self.assertIsNone(other.context["plan"])
        self.assertEqual(other.context["monthly"], Decimal("10.00"))
        self.assertEqual(self.client.post(personal_url, {"sales_floor":"1"}).status_code, 200)
        self.assertEqual(SalesTargetBand.objects.count(), 2)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(personal_url).status_code, 403)

    def test_deposit_receipt_is_visible_even_before_its_goal_is_set(self):
        self._transaction("40000000", description="بیعانه", origin="afsariyeh", owner=self.flower)
        self.client.force_login(self.flower)
        page = self.client.get(reverse("my_sales_targets"))
        self.assertContains(page, "بیعانهٔ تأییدشده دارید")
        self.assertContains(page, "کف بیعانه تعیین نشده")
        self.assertNotContains(page, 'class="cc-dial-needle"')

    def test_call_center_needle_uses_the_configured_scale_even_above_target(self):
        from types import SimpleNamespace
        from core.sales_target_views import MILLION_TOMAN_RIAL, _call_center_gauge

        plans = {"call_center": SimpleNamespace(
            heavy_limit=Decimal("40"), sales_floor=Decimal("100"),
            target_one=Decimal("130"), target_two=Decimal("160"),
        )}
        def dial(sales):
            return _call_center_gauge("call_center", "ماهانه", Decimal(sales) * MILLION_TOMAN_RIAL, plans)

        empty, halfway, above = dial("0"), dial("96"), dial("900")
        self.assertEqual([g["needle_angle"] for g in (empty, halfway, above)], ["155.0000", "270.0000", "385.0000"])
        self.assertEqual(halfway["level"], "light")
        self.assertEqual(dial("130")["level"], "one")
        self.assertEqual(above["level"], "two")
        self.assertEqual(empty["segments"], above["segments"])
        self.assertEqual(len(above["segments"]), 5)

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
        flower_row = next(row for row in res.context["flower_cards"] if row["key"] == f"flower:{self.flower.pk}")
        self.assertEqual(flower_row["value"], Decimal("13.00"))
        self.assertEqual(res.context["overall"]["value"], Decimal("18.00"))

    def test_branch_cards_display_floor_not_duplicate_sale(self):
        self.client.post(self.url, {
            "year": self.year, "month": self.month,
            "action": "set_floor", "subject": f"branch:{self.branch.pk}",
            "sales_floor": "7000",
        })
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "<small>کف</small>", html=False)
        self.assertNotContains(response, "<small>فروش</small>", html=False)
        self.assertContains(response, "7000", html=False)

    def test_target_one_is_100_percent_and_target_two_above_100(self):
        from core.sales_target_views import _gauge_row
        from types import SimpleNamespace
        plan = SimpleNamespace(
            heavy_limit=Decimal("70"), sales_floor=Decimal("100"),
            target_one=Decimal("130"), target_two=Decimal("160"),
        )
        goals = {"branch:1": plan}
        at_one = _gauge_row("branch:1", "مرکز", Decimal("130"), goals)
        self.assertEqual(at_one["percentage"], 100)
        self.assertEqual(at_one["level"], "one")
        at_two = _gauge_row("branch:1", "مرکز", Decimal("160"), goals)
        self.assertEqual(at_two["percentage"], 123)
        self.assertEqual(at_two["level"], "two")
        below = _gauge_row("branch:1", "مرکز", Decimal("65"), goals)
        self.assertEqual(below["percentage"], 50)
        self.assertEqual(below["level"], "heavy")

    def test_azar_rollover_copies_missing_aban_targets_only(self):
        import importlib
        from django.apps import apps
        from django.db import connection
        from core.models import TargetPercentPolicy
        prior = (1405, 8)
        this_month = (1405, 9)
        TargetPercentPolicy.objects.create(
            period_year=prior[0], period_month=prior[1],
            heavy_percent=Decimal("55"),
            target_one_percent=Decimal("140"),
            target_two_percent=Decimal("175"),
        )
        def legacy(scope, subject, floor, branch=None, employee=None):
            SalesTargetBand.objects.create(
                key=f"1405-08:{subject}", scope=scope,
                period_year=prior[0], period_month=prior[1],
                branch=branch, employee=employee,
                heavy_limit=Decimal(floor) * Decimal(".55"),
                sales_floor=Decimal(floor),
                target_one=Decimal(floor) * Decimal("1.4"),
                target_two=Decimal(floor) * Decimal("1.75"),
            )
        legacy("overall", "overall", "8000")
        legacy("branch", f"branch:{self.branch.pk}", "4500", branch=self.branch)
        legacy("flower", f"flower:{self.flower.pk}", "300", employee=self.flower)
        legacy("call_center", "call_center", "500")
        legacy("branch", f"branch:{self.closed.pk}", "900", branch=self.closed)
        # Previously configured Azar row is authoritative; never overwrite it.
        SalesTargetBand.objects.create(
            key="1405-09:overall", scope="overall",
            period_year=this_month[0], period_month=this_month[1],
            heavy_limit=Decimal("700"), sales_floor=Decimal("1000"),
            target_one=Decimal("1300"), target_two=Decimal("1600"),
        )
        rollover = importlib.import_module(
            "core.migrations.0137_copy_aban_targets_to_azar_1405"
        ).copy_aban_to_azar
        from types import SimpleNamespace
        editor = SimpleNamespace(connection=connection)
        rollover(apps, editor)
        rollover(apps, editor)
        azar = SalesTargetBand.objects.filter(period_year=1405, period_month=9)
        self.assertEqual(azar.count(), 4)
        self.assertEqual(azar.get(key="1405-09:overall").sales_floor, Decimal("1000"))
        copied = azar.get(key=f"1405-09:branch:{self.branch.pk}")
        self.assertEqual(copied.sales_floor, Decimal("4500"))
        self.assertEqual(copied.target_one, Decimal("6300"))
        self.assertFalse(azar.filter(key=f"1405-09:branch:{self.closed.pk}").exists())
        self.assertEqual(azar.get(key="1405-09:call_center").sales_floor, Decimal("500"))
        self.assertEqual(azar.get(key=f"1405-09:flower:{self.flower.pk}").sales_floor, Decimal("300"))
        policy = TargetPercentPolicy.objects.get(period_year=1405, period_month=9)
        self.assertEqual(policy.heavy_percent, Decimal("55"))
        self.assertEqual(policy.target_one_percent, Decimal("140"))
        self.assertEqual(policy.target_two_percent, Decimal("175"))

    def test_non_management_user_forbidden(self):
        self.client.force_login(self.staff)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 403)
        response = self.client.post(self.url, {"subject":"overall","target_one":"1"})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(SalesTargetBand.objects.count(), 0)
