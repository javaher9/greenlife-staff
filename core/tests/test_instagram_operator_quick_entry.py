"""Regression checks for Laleh's restricted Instagram DM lead entry link."""
import hashlib
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from core.instagram_views import _INSTAGRAM_OPERATOR_LINKS
from core.models import Branch, EmployeeProfile, ReferralLead


class InstagramOperatorQuickEntryTests(TestCase):
    def setUp(self):
        cache.clear()
        self.token = "quick-entry-unit-test-token-do-not-use-in-production"
        self.digest = hashlib.sha256(self.token.encode()).hexdigest()
        self.url = reverse(
            "instagram_operator_quick_lead",
            kwargs={"operator": "laleh", "token": self.token}
        )
        self.branch = Branch.objects.create(name="DM quick tests")
        self.user = User.objects.create_user(
            username="test-laleh-operator",
            first_name="شیما", last_name="عباسی", password="test"
        )
        self.staff = EmployeeProfile.objects.create(
            user=self.user, branch=self.branch,
            role="employee", can_register_instagram_dm_lead=True
        )
        self.cc_user = User.objects.create_user(
            username="test-insta-call-center", password="test"
        )
        self.cc = EmployeeProfile.objects.create(
            user=self.cc_user, branch=self.branch, role="call_center"
        )

    def get(self):
        with patch.dict(_INSTAGRAM_OPERATOR_LINKS, {"laleh": self.digest}):
            return self.client.get(self.url)

    def post(self, phone="09129876543"):
        with patch.dict(_INSTAGRAM_OPERATOR_LINKS, {"laleh": self.digest}):
            return self.client.post(self.url, {
                "full_name": "اینستاگرام تست",
                "phone": phone,
                "interested_service": "درخواست مشاوره لاغری",
                "instagram_page": "greenlifeclinics",
            })

    def test_mobile_and_desktop_use_normal_post_form(self):
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="manualInstagramForm"')
        self.assertContains(response, 'method="post"')
        self.assertNotContains(response, "event.preventDefault()")
        self.assertNotContains(response, "fetch(form.action")

    def test_real_save_returns_reference_and_assigns_to_call_center(self):
        response = self.post()
        self.assertEqual(response.status_code, 200)
        lead = ReferralLead.objects.get(phone="09129876543")
        self.assertEqual(lead.created_by_id, self.user.pk)
        self.assertEqual(lead.assigned_to_id, self.cc.pk)
        self.assertIn("ثبت از دایرکت توسط", lead.notes)
        self.assertContains(response, f"شماره پیگیری: {lead.pk}")
        self.assertContains(response, "به صف کال‌سنتر تخصیص داده شد")

    def test_duplicate_is_not_misreported_as_success(self):
        self.post()
        second = self.post()
        self.assertEqual(second.status_code, 200)
        self.assertNotContains(second, '<div class="success">')
        self.assertContains(second, "ثبت انجام نشد")
        self.assertEqual(ReferralLead.objects.filter(phone="09129876543").count(), 1)

    def test_no_active_call_center_does_not_claim_assignment(self):
        self.cc.is_active = False
        self.cc.save(update_fields=["is_active"])
        response = self.post()
        self.assertEqual(response.status_code, 200)
        lead = ReferralLead.objects.get(phone="09129876543")
        self.assertIsNone(lead.assigned_to)
        self.assertContains(response, f"شماره پیگیری: {lead.pk}")
        self.assertContains(response, "اپراتور فعالی برای تخصیص پیدا نشد")

    def test_same_surname_does_not_block_known_laleh_identity(self):
        other_user = User.objects.create_user(
            username="another-abbasi", first_name="سارا",
            last_name="عباسی", password="test"
        )
        EmployeeProfile.objects.create(user=other_user, branch=self.branch, role="employee")
        response = self.post()
        self.assertEqual(response.status_code, 200)
        lead = ReferralLead.objects.get(phone="09129876543")
        self.assertEqual(lead.created_by_id, self.user.pk)

    def test_truly_ambiguous_full_identity_blocks_wrong_attribution(self):
        other_user = User.objects.create_user(
            username="another-shima-abbasi", first_name="شیما",
            last_name="عباسی", password="test"
        )
        EmployeeProfile.objects.create(
            user=other_user, branch=self.branch, role="employee",
            can_register_instagram_dm_lead=True
        )
        response = self.get()
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "حساب ثبت‌کننده نیاز به بررسی مدیریت دارد", status_code=503)
        self.assertFalse(ReferralLead.objects.exists())

    def test_rate_limit_returns_farsi_error_and_retains_posted_form(self):
        with patch("django.core.cache.cache.get", return_value=120):
            response = self.post()
        self.assertEqual(response.status_code, 429)
        self.assertContains(response, "تعداد تلاش‌های ثبت", status_code=429)
        self.assertContains(response, "09129876543", status_code=429)
        self.assertFalse(ReferralLead.objects.exists())
