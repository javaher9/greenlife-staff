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
                self.assertContains(response, 'data-main-phone="02191002000"')
                self.assertContains(response, 'data-inbound-phone="02134247"')
                self.assertContains(response, f'data-user-id="{user.pk}"')
                self.assertContains(response, 'phone-center-readiness.js')
                self.assertContains(response, 'phone-center-activity.js')
                self.assertContains(response, 'phone-center-assistants.js')
                self.assertContains(response, f'data-follow-ups="{reverse("phone_center_follow_ups")}"')
                for assistant in ('یاسمن', 'کاملیا', 'رز'):
                    self.assertContains(response, f'<h3>{assistant}</h3>')
                self.assertContains(response, 'phone-center.js')
                self.assertIn('no-store', response.headers['Cache-Control'])
                self.assertEqual(self.client.post(url).status_code, 405)

    def test_phone_follow_ups_uses_the_management_queue_with_phone_center_access(self):
        url = reverse('phone_center_follow_ups')
        self.assertRedirects(self.client.get(url), f'/login/?next={url}', fetch_redirect_response=False)
        self.client.force_login(self.branch_manager)
        self.assertEqual(self.client.get(url).status_code, 403)
        for user in (self.admin, self.internal_manager):
            with self.subTest(user=user):
                self.client.force_login(user)
                response = self.client.get(url, {'tab': 'done'})
                self.assertTemplateUsed(response, 'core/call_center/follow_up_management.html')
                self.assertContains(response, f'href="{reverse("phone_center")}"')
                self.assertEqual(response.context['tab'], 'done')
                self.assertIn('no-store', response.headers['Cache-Control'])

    def test_management_home_links_to_phone_center(self):
        self.client.force_login(self.admin)
        response = self.client.get(reverse('branch_live_dashboard'))
        url = reverse('phone_center')
        self.assertContains(response, f'class="cmd-module" href="{url}"')
        # Executive navigation only groups direct links or links in a settings details element.
        self.assertRegex(
            response.content.decode(),
            rf'<a href="{reverse("branch_live_dashboard")}">[^\n]+</a>\s*<a href="{url}">',
        )
