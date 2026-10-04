from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse


@override_settings(EXECUTIVE_USERNAMES=("owner",))
class ServerHealthTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="pass-123")
        self.regular = User.objects.create_user(username="regular", password="pass-123")

    def test_executive_can_read_server_health_api(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("server_health_api"))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("server", payload)
        self.assertIn("cpu_percent", payload["server"])
        self.assertIn("memory", payload["server"])
        self.assertIn("disk", payload["server"])
        self.assertEqual(response["Cache-Control"], "no-store, private, max-age=0")

    def test_executive_can_render_server_health_page(self):
        self.client.force_login(self.owner)
        response = self.client.get(reverse("server_health"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "وضعیت زنده سرور")
        self.assertContains(response, "فقط‌خواندنی")

    def test_regular_user_is_denied(self):
        self.client.force_login(self.regular)
        response = self.client.get(reverse("server_health_api"))
        self.assertEqual(response.status_code, 403)
