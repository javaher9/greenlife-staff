from datetime import time, timedelta
from types import SimpleNamespace

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.device_booking_models import DeviceTypeSchedule, PhysicalDevice
from core.models import Branch, DeviceIssue, EmployeeProfile, VisitAppointment
from core.quality_command_views import _physical_state


class QualityCommandCenterTests(TestCase):
    def setUp(self):
        self.niavaran = Branch.objects.create(name="نیاوران QC")
        self.punak = Branch.objects.create(name="پونک QC")
        self.admin = self.person("quality-admin", "admin", self.niavaran)
        self.manager = self.person("quality-manager", "manager", self.niavaran)
        self.employee = self.person("quality-employee", "employee", self.punak)
        self.naderi = self.person(
            "quality-naderi", "employee", self.niavaran, job_title="کنترل کیفیت"
        )
        device_type = DeviceTypeSchedule.objects.create(
            code="QC-CRYO", name="کرایو تست"
        )
        self.device = PhysicalDevice.objects.create(
            branch=self.niavaran, device_type=device_type, name="کرایو A"
        )
        self.punak_device = PhysicalDevice.objects.create(
            branch=self.punak, device_type=device_type, name="کرایو B"
        )
        self.niavaran_visit = self.visit(
            self.niavaran, "بیمار نیاوران", "arrived", time(9, 0)
        )
        self.punak_visit = self.visit(
            self.punak, "بیمار پونک", "booked", time(9, 15)
        )

    @staticmethod
    def person(name, role, branch, job_title=""):
        user = User.objects.create_user(username=name, password="pass-test-123")
        EmployeeProfile.objects.update_or_create(
            user=user, defaults={
                "role": role,
                "branch": branch,
                "is_active": True,
                "job_title": job_title,
            }
        )
        return User.objects.get(pk=user.pk)

    @staticmethod
    def visit(branch, name, status, slot):
        return VisitAppointment.objects.create(
            branch=branch, full_name=name, phone="09121111111",
            appointment_date=timezone.localdate(), appointment_time=slot,
            status=status, source="receptionist",
        )

    def test_unauthorized_employee_cannot_read_html_or_live_api(self):
        self.client.force_login(self.employee)
        for url in ("quality_command_center", "quality_command_data"):
            self.assertEqual(self.client.get(reverse(url)).status_code, 403)

    def test_naderi_job_title_can_read_live_multibranch_dashboard(self):
        self.client.force_login(self.naderi)
        response = self.client.get(reverse("quality_command_center"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "بیمار نیاوران")
        self.assertContains(response, "بیمار پونک")
        self.assertContains(response, "کرایو A")
        self.assertContains(response, "کرایو B")
        self.assertContains(response, "رادار کال‌سنتر")
        self.assertEqual(response["Cache-Control"], "private, no-store")
        data = self.client.get(reverse("quality_command_data"))
        self.assertTrue(data.json()["ok"])
        self.assertIn("بیمار پونک", data.json()["html"])

    def test_manager_scope_does_not_leak_other_branch_patient(self):
        self.client.force_login(self.manager)
        response = self.client.get(reverse("quality_command_center"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "بیمار نیاوران")
        self.assertNotContains(response, "بیمار پونک")
        data = self.client.get(reverse("quality_command_data")).json()
        self.assertNotIn("بیمار پونک", data["html"])

    def test_qc_group_allows_authorized_employee_without_title(self):
        group = Group.objects.create(name="GreenLife QC")
        self.employee.groups.add(group)
        self.client.force_login(User.objects.get(pk=self.employee.pk))
        response = self.client.get(reverse("quality_command_center"))
        self.assertEqual(response.status_code, 200)

    def test_open_issue_is_reflected_in_device_state(self):
        DeviceIssue.objects.create(
            reporter=self.admin, branch=self.niavaran,
            device_name="کرایو A", description="تست هشدار",
        )
        self.client.force_login(self.admin)
        response = self.client.get(reverse("quality_command_center"))
        self.assertContains(response, "گزارش خرابی باز")
        self.assertContains(response, "1 ایراد دستگاه")

    def test_booking_alone_is_not_reported_as_active_hardware(self):
        now = timezone.now()
        booked = SimpleNamespace(
            device_id=self.device.pk, secondary_device_id=None,
            status="booked", starts_at=now-timedelta(minutes=5),
            treatment_ends_at=now+timedelta(minutes=15),
            blocked_until=now+timedelta(minutes=30),
            appointment=SimpleNamespace(full_name="بیمار تست"),
        )
        state, label, _, _ = _physical_state(self.device, [booked], set(), now)
        self.assertEqual(state, "review")
        self.assertEqual(label, "نوبت شروع‌نشده")
        booked.status = "arrived"
        state, label, _, _ = _physical_state(self.device, [booked], set(), now)
        self.assertEqual(state, "busy")
        self.assertEqual(label, "جلسه ثبت‌شده")
