import json
import os
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Branch, CallCenterLeadGroup, EmployeeProfile, ReferralLead


class TelegramAgentWebhookTests(TestCase):
    def setUp(self):
        branch = Branch.objects.create(name='کال‌سنتر')
        user = User.objects.create_user(username='telegram-agent-operator', password='x')
        self.operator = EmployeeProfile.objects.create(
            user=user,
            role='call_center',
            branch=branch,
            is_active=True,
        )

    def _post_update(self, payload, secret='test-telegram-secret'):
        return self.client.post(
            reverse('telegram_webhook'),
            data=json.dumps(payload),
            content_type='application/json',
            HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret,
        )

    @patch.dict(os.environ, {
        'TELEGRAM_WEBHOOK_SECRET': 'test-telegram-secret',
        'TELEGRAM_BOT_TOKEN': '123456:test-token',
    }, clear=False)
    @patch('core.telegram_agent._telegram_api', return_value={'ok': True})
    def test_contact_creates_call_center_lead_and_service_callback_updates_it(self, api_mock):
        contact_update = {
            'update_id': 1001,
            'message': {
                'message_id': 10,
                'chat': {'id': 778899, 'type': 'private'},
                'from': {
                    'id': 778899,
                    'first_name': 'مراجع',
                    'last_name': 'تلگرام',
                    'username': 'greenlife_test_user',
                },
                'contact': {
                    'phone_number': '09121234567',
                    'first_name': 'مراجع',
                    'user_id': 778899,
                },
            },
        }
        response = self._post_update(contact_update)
        self.assertEqual(response.status_code, 200)

        lead = ReferralLead.objects.get(phone='09121234567')
        self.assertEqual(lead.assigned_to, self.operator)
        self.assertEqual(lead.group.name, 'تلگرام - لینک')
        self.assertIn('[channel:telegram]', lead.notes)
        self.assertIn('[telegram_user:778899]', lead.notes)
        self.assertEqual(lead.source, 'link')
        self.assertTrue(
            CallCenterLeadGroup.objects.filter(owner=self.operator, name='تلگرام - لینک').exists()
        )

        callback_update = {
            'update_id': 1002,
            'callback_query': {
                'id': 'callback-1',
                'from': {'id': 778899, 'first_name': 'مراجع'},
                'data': f'glsvc:{lead.id}:0',
                'message': {
                    'message_id': 11,
                    'chat': {'id': 778899, 'type': 'private'},
                },
            },
        }
        response = self._post_update(callback_update)
        self.assertEqual(response.status_code, 200)
        lead.refresh_from_db()
        self.assertEqual(lead.interested_service, 'لاغری')
        self.assertIn('[telegram_service:لاغری]', lead.notes)
        self.assertGreaterEqual(api_mock.call_count, 3)

    @patch.dict(os.environ, {
        'TELEGRAM_WEBHOOK_SECRET': 'test-telegram-secret',
    }, clear=False)
    def test_wrong_webhook_secret_is_rejected(self):
        response = self._post_update({'update_id': 2001}, secret='wrong-secret')
        self.assertEqual(response.status_code, 403)
        self.assertEqual(ReferralLead.objects.count(), 0)
