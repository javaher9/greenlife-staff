from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from core.models import EmployeeProfile
from core.phone_supervision import SupervisionError


class PhoneControlTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.admin = users.objects.create_user(username='phone-supervisor')
        cls.manager = users.objects.create_user(username='phone-internal-manager')
        cls.operator = users.objects.create_user(username='phone-operator')
        for user, role in (
            (cls.admin, 'admin'), (cls.manager, 'internal_manager'), (cls.operator, 'call_center'),
        ):
            EmployeeProfile.objects.update_or_create(user=user, defaults={'role': role, 'is_active': True})

    def test_control_requires_management_and_links_from_phone_center(self):
        control = reverse('phone_center_control')
        self.assertRedirects(self.client.get(control), f'/login/?next={control}', fetch_redirect_response=False)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(control).status_code, 403)
        self.assertEqual(self.client.get(reverse('phone_center_live')).status_code, 403)
        for manager in (self.admin, self.manager):
            self.client.force_login(manager)
            page = self.client.get(control)
            self.assertContains(page, 'کنترل تماس گرین‌لایف')
            self.assertContains(page, 'راهنمایی خصوصی')
            self.assertContains(page, 'در بازهٔ انتخاب‌شده امتیازی ثبت نشده است.')
            self.assertContains(page, reverse('phone_assistant_queue'))
            self.assertIn('no-store', page.headers['Cache-Control'])
            self.assertContains(self.client.get(reverse('phone_center')), f'href="{control}"')

    def test_live_snapshot_is_honest_without_connection(self):
        self.client.force_login(self.admin)
        with patch.dict('os.environ', {'GREENLIFE_SUPERVISION_AMI': ''}):
            response = self.client.get(reverse('phone_center_live'))
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertFalse(response.json()['available'])
        self.assertEqual(response.json()['calls'], [])

    def test_supervision_post_enforces_csrf_and_exact_arguments(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        client.get(reverse('phone_center_control'))
        url = reverse('phone_center_live')
        data = {'call_id': 'a' * 64, 'mode': 'whisper'}
        with patch('core.phone_control_views.start_supervision', return_value={'accepted': True}) as start:
            rejected = client.post(url, data, content_type='application/json')
            self.assertRedirects(rejected, url, fetch_redirect_response=False)
            start.assert_not_called()
            csrf = {'HTTP_X_CSRFTOKEN': client.cookies['csrftoken'].value}
            error = client.post(url, {**data, 'extension': '201'}, content_type='application/json', **csrf)
            self.assertEqual(error.status_code, 400)
            start.assert_not_called()
            accepted = client.post(url, data, content_type='application/json', **csrf)
            self.assertEqual(accepted.status_code, 202)
            start.assert_called_once_with(self.admin, data['call_id'], 'whisper')

    def test_server_reports_stale_call_and_never_claims_success(self):
        self.client.force_login(self.admin)
        with patch('core.phone_control_views.start_supervision', side_effect=SupervisionError('stale', 'پایان تماس', 409)):
            response = self.client.post(reverse('phone_center_live'), {
                'call_id': 'a' * 64, 'mode': 'join',
            }, content_type='application/json')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json(), {'code': 'stale', 'message': 'پایان تماس'})
