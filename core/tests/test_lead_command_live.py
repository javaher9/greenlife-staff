"""Lead Command reads real, privacy-safe CRM intake data; no fake worker activity."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Country, EmployeeProfile, ReferralLead, ReferralProfile, MarketingWorkerState
from core.management.commands.run_marketing_monitor import monitor_once


class LeadCommandLiveTests(TestCase):
    def setUp(self):
        self.ir, _ = Country.objects.get_or_create(
            code="IR", defaults={"name_english": "Iran", "name_local": "ایران"},
        )
        self.tr, _ = Country.objects.get_or_create(
            code="TR", defaults={"name_english": "Turkey", "name_local": "ترکیه"},
        )
        self.admin = User.objects.create_user(username="lcc-admin", password="test-password")
        EmployeeProfile.objects.update_or_create(
            user=self.admin, defaults={"role": "admin", "country": self.ir, "is_active": True}
        )
        source_user = User.objects.create_user(username="lcc-referrer", password="test-password")
        self.source = ReferralProfile.objects.create(
            user=source_user, referral_code="LCC-TEST-REF",
        )

    def _lead(self, phone, country, full_name="لید آزمایشی"):
        return ReferralLead.objects.create(
            referrer=self.source, full_name=full_name, phone=phone, country=country
        )

    def test_recent_iran_records_count_but_no_personal_data_in_json(self):
        self._lead("09121111234", self.ir, "نام محرمانه مشتری")
        self._lead("09121111235", self.tr, "مشتری خارج ایران")
        self.client.force_login(self.admin)
        res = self.client.get(reverse("lead_command_center_live"))
        self.assertEqual(res.status_code, 200)
        snapshot = res.json()
        self.assertEqual(snapshot["kpi"]["new_today"], 1)
        self.assertEqual(snapshot["kpi"]["active"], 0)
        self.assertIsNone(snapshot["kpi"]["qualified_today"])
        self.assertIsNone(snapshot["kpi"]["revenue_today"])
        self.assertEqual(len(snapshot["events"]), 1)
        self.assertTrue(all(agent["status"] == "waiting" for agent in snapshot["agents"]))
        self.assertNotIn("09121111234", res.content.decode("utf-8"))
        self.assertNotIn("نام محرمانه مشتری", res.content.decode("utf-8"))

    def test_yesterday_leads_are_excluded(self):
        previous = self._lead("09121111236", self.ir)
        ReferralLead.objects.filter(pk=previous.pk).update(
            created_at=timezone.now() - timedelta(days=2)
        )
        self.client.force_login(self.admin)
        snapshot = self.client.get(reverse("lead_command_center_live")).json()
        self.assertEqual(snapshot["kpi"]["new_today"], 0)
        self.assertEqual(snapshot["events"], [])

    def test_ordinary_employee_is_denied_both_routes(self):
        employee = User.objects.create_user(username="lcc-employee", password="test-password")
        EmployeeProfile.objects.update_or_create(
            user=employee, defaults={"role": "employee", "is_active": True}
        )
        self.client.force_login(employee)
        self.assertEqual(self.client.get(reverse("lead_command_center")).status_code, 403)
        self.assertEqual(self.client.get(reverse("lead_command_center_live")).status_code, 403)

    def test_running_requires_real_recent_monitor_heartbeat(self):
        self.client.force_login(self.admin)
        snapshot = self.client.get(reverse("lead_command_center_live")).json()
        self.assertEqual(snapshot["kpi"]["active"], 0)
        self._lead("09121111238", self.ir)
        self.assertEqual(monitor_once(), 1)
        self.assertEqual(ReferralLead.objects.count(), 1)
        snapshot = self.client.get(reverse("lead_command_center_live")).json()
        self.assertEqual(snapshot["kpi"]["active"], 1)
        running = [a for a in snapshot["agents"] if a["status"] == "running"]
        self.assertEqual([a["key"] for a in running], ["commander"])
        self.assertEqual(snapshot["kpi"]["new_today"], 1)
        self.assertTrue(running[0]["heartbeat"])

    def test_stale_monitor_does_not_pretend_active(self):
        MarketingWorkerState.objects.create(
            key="commander",
            heartbeat_at=timezone.now()-timedelta(minutes=5),
            last_run_leads=5,
            activity="old heartbeat",
        )
        self.client.force_login(self.admin)
        snapshot = self.client.get(reverse("lead_command_center_live")).json()
        self.assertEqual(snapshot["kpi"]["active"], 0)
        self.assertTrue(all(a["status"] == "waiting" for a in snapshot["agents"]))
        self.assertEqual(snapshot["kpi"]["new_today"], 0)
