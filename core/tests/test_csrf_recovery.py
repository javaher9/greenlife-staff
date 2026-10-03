from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse

from core.models import Branch, EmployeeProfile


class CsrfRecoveryTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='CSRF Test')
        self.user=User.objects.create_user('consultant-csrf',password='pass')
        EmployeeProfile.objects.create(
            user=self.user,branch=self.branch,role='consultant',is_active=True,
        )

    def test_authenticated_stale_csrf_recovers_with_get_redirect(self):
        client=Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response=client.post(
            reverse('consultant_sales_outcomes'),
            {'action':'finalize','appointment_id':'999999'},
            HTTP_REFERER='https://staff.greenlifeclinics.com/consultant/',
            HTTP_HOST='staff.greenlifeclinics.com',
            secure=True,
        )
        self.assertEqual(response.status_code,302)
        self.assertEqual(response['Location'],'https://staff.greenlifeclinics.com/consultant/')

    def test_anonymous_csrf_failure_stays_forbidden(self):
        client=Client(enforce_csrf_checks=True)
        response=client.post(
            reverse('consultant_sales_outcomes'),
            {'action':'finalize'},
            HTTP_HOST='staff.greenlifeclinics.com',
            secure=True,
        )
        self.assertEqual(response.status_code,403)
