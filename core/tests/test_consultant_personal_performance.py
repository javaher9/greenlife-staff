"""Branch-scoped personal consultation funnel on the consultant home page."""
from datetime import time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.consultant_sales_views import _personal_consultant_performance
from core.models import Branch, ConsultationPlan, EmployeeProfile, VisitAppointment


class ConsultantPersonalPerformanceTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name="Performance main")
        self.other_branch = Branch.objects.create(name="Performance other")
        self.user = User.objects.create_user("performance-consultant", password="test")
        self.other_user = User.objects.create_user("other-performance-consultant", password="test")
        self.profile = EmployeeProfile.objects.create(
            user=self.user, branch=self.branch, role="consultant"
        )
        self._counter = 0

    def make_plan(self, consultant, branch, status, *, date=None, appointment_status="completed", proposed=False):
        self._counter += 1
        slot = time(10 + self._counter // 4, (self._counter % 4) * 15)
        appointment = VisitAppointment.objects.create(
            branch=branch,
            full_name="Performance case",
            phone=f"0912000{self._counter:04d}",
            appointment_date=date or timezone.localdate(),
            appointment_time=slot,
            status=appointment_status,
            care_stage="closed",
        )
        return ConsultationPlan.objects.create(
            appointment=appointment, consultant=consultant, status=status,
            finalized_at=timezone.now() if proposed else None,
        )

    def test_only_this_consultants_recorded_outcomes_count(self):
        self.make_plan(self.user, self.branch, "draft")
        self.make_plan(self.user, self.branch, "no_sale")
        self.make_plan(self.user, self.branch, "finalized", proposed=True)
        self.make_plan(self.user, self.branch, "partial_paid", proposed=True)
        self.make_plan(self.user, self.branch, "paid", proposed=True)
        self.make_plan(self.other_user, self.branch, "paid", proposed=True)
        self.make_plan(self.user, self.other_branch, "paid", proposed=True)
        self.make_plan(self.user, self.branch, "paid", appointment_status="no_show", proposed=True)
        self.make_plan(self.user, self.branch, "paid", date=timezone.localdate() - timedelta(days=40), proposed=True)

        stats = _personal_consultant_performance(self.profile)
        self.assertEqual(stats["consultations"], 4)
        self.assertEqual(stats["proposals"], 3)
        self.assertEqual(stats["sales"], 1)
        self.assertEqual(stats["conversion"], 25)
        self.assertEqual(stats["consultations_width"], 100)
        self.assertEqual(stats["proposals_width"], 75)
        self.assertEqual(stats["sales_width"], 25)

    def test_no_results_shows_no_conversion_instead_of_a_fake_zero(self):
        stats = _personal_consultant_performance(self.profile)
        self.assertEqual(stats["consultations"], 0)
        self.assertEqual(stats["proposals"], 0)
        self.assertEqual(stats["sales"], 0)
        self.assertIsNone(stats["conversion"])
        self.assertFalse(stats["has_data"])
        self.assertEqual(stats["consultations_width"], 0)
