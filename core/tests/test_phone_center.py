from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import EmployeeProfile


class PhoneCenterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.admin = users.objects.create_user(username='phone-center-admin')
        cls.internal_manager = users.objects.create_user(username='phone-center-internal')
        cls.branch_manager = users.objects.create_user(username='phone-center-branch')
        for user, role in (
            (cls.admin, 'admin'),
            (cls.internal_manager, 'internal_manager'),
            (cls.branch_manager, 'manager'),
        ):
            EmployeeProfile.objects.update_or_create(user=user, defaults={'role': role, 'is_active': True})

    def test_phone_center_requires_management_access(self):
        url = reverse('phone_center')
        self.assertRedirects(self.client.get(url), f'/login/?next={url}', fetch_redirect_response=False)
        self.client.force_login(self.branch_manager)
        self.assertEqual(self.client.get(url).status_code, 403)
        for user in (self.admin, self.internal_manager):
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(url)
                self.assertContains(response, 'مرکز تلفن گرین‌لایف')
                self.assertContains(response, '02191002000')
                self.assertContains(response, 'داده‌های نمونه')
                self.assertIn('no-store', response.headers['Cache-Control'])
                self.assertEqual(self.client.post(url).status_code, 405)

    def test_management_home_links_to_phone_center(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('branch_live_dashboard'))
        self.assertContains(response, f'href="{reverse("phone_center")}"')
