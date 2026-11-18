from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import InstagramIntegrationSettings, InstagramWebhookEvent, WhatsAppMessage, WhatsAppNumber


@override_settings(EXECUTIVE_USERNAMES=['owner'])
class AgentActivityTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='owner')
        self.snapshot = reverse('agent_activity_snapshot')

    def test_page_and_snapshot_are_executive_only(self):
        page = reverse('agent_activity')
        self.assertEqual(self.client.get(self.snapshot).status_code, 302)
        self.client.force_login(get_user_model().objects.create_user(username='staff'))
        self.assertEqual(self.client.get(page).status_code, 403)
        self.assertEqual(self.client.get(self.snapshot).status_code, 403)

        self.client.force_login(self.owner)
        self.assertContains(self.client.get(page), 'اتاق فرمان کانال‌ها')
        self.assertIn('no-store', self.client.get(self.snapshot)['Cache-Control'])

    def test_snapshot_counts_real_inbound_activity_without_message_content(self):
        InstagramIntegrationSettings.objects.create(
            pk=1, username='greenlifeclinics', app_id='app', app_secret_cipher='configured',
            instagram_user_id='1234', access_token_cipher='connected', is_enabled=True,
        )
        message = {'message': {'mid': 'external-id', 'text': 'private Instagram message'}}
        echo = {'message': {'mid': 'echo', 'is_echo': True}}
        for event_hash, account in [('a', '1234'), ('b', '1234'), ('c', '9999')]:
            InstagramWebhookEvent.objects.create(event_hash=event_hash, payload={
                'object': 'instagram', 'entry': [{'id': account, 'messaging': [message, echo]}],
            })
        number = WhatsAppNumber.objects.create(label='نیاوران', phone_number='1000', connection_status='connected')
        WhatsAppNumber.objects.create(label='پونک', phone_number='2000')
        for direction, status in [('inbound', 'received'), ('outbound', 'sent'), ('outbound', 'queued')]:
            WhatsAppMessage.objects.create(
                whatsapp_number=number, direction=direction, status=status,
                contact_phone='123456789', body='private WhatsApp message',
            )

        self.client.force_login(self.owner)
        response = self.client.get(self.snapshot)
        channels = {channel['id']: channel for channel in response.json()['channels']}
        self.assertEqual(channels['instagram']['count'], 1)
        self.assertEqual(channels[f'wa-{number.pk}']['count'], 1)
        self.assertEqual(channels['bale']['tone'], 'pending')
        self.assertEqual(len(response.json()['events']), 3)
        for private_value in ['private WhatsApp', 'private Instagram', '123456789', 'external-id']:
            self.assertNotContains(response, private_value)
