from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from core.infrastructure_models import InfrastructureBalanceCheck, InfrastructureService


class InfrastructureAuditPermissionsTests(TestCase):
    def setUp(self):
        self.url = reverse("infrastructure_dashboard")
        self.auditor = User.objects.create_user("infrastructure_auditor", password="unused-long-test-password")
        self.outsider = User.objects.create_user("infrastructure_outsider", password="unused-long-test-password")
        group, _ = Group.objects.get_or_create(name="GreenLife Infrastructure Audit")
        self.auditor.groups.add(group)
        self.service = InfrastructureService.objects.create(
            label="اینترنت آزمایشی", kind="internet", provider="شرکت آزمایشی",
        )

    def test_outsider_cannot_view_or_post(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.post(self.url, {
            "service_id": self.service.pk, "status": "clear", "source": "portal",
        }).status_code, 403)
        self.assertEqual(InfrastructureBalanceCheck.objects.count(), 0)

    def test_auditor_can_report_without_editing_service(self):
        self.client.force_login(self.auditor)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        response = self.client.post(self.url, {
            "service_id": self.service.pk,
            "status": "owed", "amount_due": "2500000",
            "source": "bill", "note": "فاکتور ارائه‌دهنده",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(InfrastructureBalanceCheck.objects.count(), 1)
        self.service.refresh_from_db()
        self.assertFalse(self.service.company_controls_recovery)

    def test_auditor_cannot_report_debt_without_amount(self):
        self.client.force_login(self.auditor)
        response = self.client.post(self.url, {
            "service_id": self.service.pk, "status": "owed", "source": "portal",
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(InfrastructureBalanceCheck.objects.count(), 0)
