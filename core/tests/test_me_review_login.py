import re
from unittest.mock import Mock, patch

from django.conf import settings
from django.test import Client, TestCase
from django.urls import reverse

from core.models import CustomerPortalMember


class MemberReviewLoginTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        self.host = {"secure": True, "HTTP_HOST": "app.greenlifeclinics.com"}
        self.login = reverse("customer_login")
        self.next = "/customer/me/connect/"
        self.review = "https://greenlife-me-review-rejimir.vercel.app"
        self.pinned = "https://greenlife-me-preview-l9fc2y2pg-rejimir.vercel.app"

    def open_form(self):
        response = self.client.get(self.login, {"next": self.next}, **self.host)
        self.assertEqual(response.status_code, 200)
        return response.context["csrf_token"]

    @patch("core.customer_portal_views.send_sms")
    def test_review_login_verifies_sms_before_connecting(self, sms):
        sms.return_value = (Mock(pk=1234), {})
        token = self.open_form()
        response = self.client.post(
            self.login, {"action": "send", "phone": "۰۹۱۲۳۴۵۶۷۸۹", "csrfmiddlewaretoken": str(token)},
            HTTP_ORIGIN=self.review, **self.host,
        )
        self.assertContains(response, 'id="verify-code"')
        self.assertFalse(CustomerPortalMember.objects.exists())
        self.assertEqual(self.client.get("/customer/me/state/", **self.host).status_code, 401)
        code = re.search(r"(?<!\d)\d{6}(?!\d)", sms.call_args.args[1]).group()
        verified = self.client.post(
            self.login, {"action": "verify", "code": code, "csrfmiddlewaretoken": str(response.context["csrf_token"])},
            HTTP_ORIGIN=self.review, **self.host,
        )
        self.assertRedirects(verified, self.next, fetch_redirect_response=False)
        self.assertTrue(self.client.get("/customer/me/state/", **self.host).json()["authenticated"])
        sms.assert_called_once()

    @patch("core.customer_portal_views.send_sms")
    def test_both_review_hosts_reach_form_validation(self, sms):
        form = {"action": "send", "phone": "12", "csrfmiddlewaretoken": str(self.open_form())}
        for origin in (self.review, self.pinned):
            for header in ({"HTTP_ORIGIN": origin}, {"HTTP_REFERER": origin + self.login}):
                with self.subTest(origin=origin, header=list(header)):
                    response = self.client.post(self.login, form, **self.host, **header)
                    self.assertContains(response, "شماره موبایل معتبر وارد کنید")
        sms.assert_not_called()

    @patch("core.customer_portal_views.send_sms")
    def test_review_stays_scoped_to_customer_and_requires_token(self, sms):
        form = {"action": "send", "phone": "12", "csrfmiddlewaretoken": str(self.open_form())}
        self.assertNotIn(self.review, settings.CSRF_TRUSTED_ORIGINS)
        unrelated = "https://unrelated-preview.vercel.app"
        for url, fields, headers in (
            (self.login, {"action": "send", "phone": "12"}, {"HTTP_ORIGIN": self.review}),
            (self.login, form, {"HTTP_ORIGIN": unrelated}),
            (self.login, form, {"HTTP_REFERER": unrelated + self.login}),
            (reverse("login"), form, {"HTTP_ORIGIN": self.review}),
            (reverse("login"), form, {"HTTP_REFERER": self.review + self.login}),
        ):
            with self.subTest(path=url, headers=list(headers), has_token="csrfmiddlewaretoken" in fields):
                self.assertEqual(self.client.post(url, fields, **self.host, **headers).status_code, 403)
        sms.assert_not_called()
