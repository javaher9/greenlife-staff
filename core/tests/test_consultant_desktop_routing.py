from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Branch, EmployeeProfile


class ConsultantDesktopRoutingTests(TestCase):
    def setUp(self):
        branch=Branch.objects.create(name='Consultant desktop test')
        self.consultant=User.objects.create_user('consultant-desktop',password='pass')
        EmployeeProfile.objects.update_or_create(
            user=self.consultant,
            defaults={'role':'consultant','branch':branch,'is_active':True},
        )
        self.client.force_login(self.consultant)

    def test_desktop_home_opens_consultant_sales_workspace(self):
        response=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36',
            HTTP_SEC_CH_UA_MOBILE='?0',
        )
        self.assertRedirects(response,reverse('consultant_sales_outcomes'))
        page=self.client.get(
            reverse('consultant_sales_outcomes'),
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        )
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'پنل مشاور')

    def test_phone_keeps_personnel_home(self):
        response=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 16; Pixel 9) Chrome/140 Mobile Safari/537.36',
            HTTP_SEC_CH_UA_MOBILE='?1',
        )
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,'core/dashboard.html')

    def test_desktop_receptionist_route_stays_unchanged(self):
        self.consultant.profile.role='receptionist'
        self.consultant.profile.save(update_fields=['role'])
        response=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        )
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,'core/receptionist_dashboard.html')
