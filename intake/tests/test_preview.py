from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from core.models import StaffNotification, VisitAppointment
from intake.models import IntakeInvitation
from intake.views import LIMITED_CHOICES


class WeightPreviewTests(TestCase):
    def test_public_preview_contains_all_conditions_and_eight_images(self):
        response = self.client.get(reverse("intake_weight_preview"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "intake/weight_form.html")
        self.assertContains(response, "نسخه آزمایشی")
        for condition in LIMITED_CHOICES["conditions"]:
            self.assertContains(response, condition)
        self.assertContains(response, 'class="intake-banner"', count=8)
        self.assertEqual(response["X-Robots-Tag"], "noindex, nofollow")
        self.assertIn("no-store", response["Cache-Control"])

    @patch("intake.views.send_sms")
    def test_preview_submission_creates_no_records_or_sms(self, send_sms):
        models = (VisitAppointment, IntakeInvitation, StaffNotification)
        before = [model.objects.count() for model in models]
        response = self.client.post(reverse("intake_weight_preview"), {
            "conditions": ["دیابت"], "medications": "DEMO-DO-NOT-SAVE",
            "consent": "on",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "intake/preview_finished.html")
        self.assertNotContains(response, "DEMO-DO-NOT-SAVE")
        self.assertEqual(before, [model.objects.count() for model in models])
        send_sms.assert_not_called()

    def test_preview_keeps_csrf_and_rejects_other_methods(self):
        client = Client(enforce_csrf_checks=True)
        url = reverse("intake_weight_preview")
        self.assertEqual(client.post(url, {}).status_code, 403)
        response = client.get(url)
        token = response.cookies["csrftoken"].value
        self.assertEqual(client.post(url, {}, HTTP_X_CSRFTOKEN=token).status_code, 200)
        self.assertEqual(self.client.put(url).status_code, 405)
