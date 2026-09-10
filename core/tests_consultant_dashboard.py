from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Branch, EmployeeProfile


class ConsultantDashboardTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Test Consultant Branch')
        self.user = User.objects.create_user(username='consultant_test', password='pass12345')
        EmployeeProfile.objects.create(user=self.user, branch=self.branch, role='consultant')

    def test_consultant_route_renders_for_consultant(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('consultant_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'پنل مشاور')
        self.assertContains(response, 'Happy Call')
        self.assertContains(response, 'پرزنت به مراجع')

    def test_root_redirects_desktop_consultant(self):
        self.client.force_login(self.user)
        response = self.client.get('/', HTTP_USER_AGENT='Mozilla/5.0 (X11; Linux x86_64)')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('consultant_dashboard'))
