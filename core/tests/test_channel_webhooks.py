from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import ChannelMessageReceipt


TELEGRAM_SECRET = 'telegram_webhook_secret_1111111111111111'
BALE_SECRET = 'bale_webhook_secret_22222222222222222222'


@override_settings(
    CHANNEL_BOTS={
        'telegram': ('111:token_for_testing_only_telegram', TELEGRAM_SECRET),
        'bale': ('222:token_for_testing_only_bale', BALE_SECRET),
    },
    PUBLIC_BASE_URL='https://staff.example.com',
    EXECUTIVE_USERNAMES=['owner'],
)
class ChannelWebhookTests(TestCase):
    def test_only_authorized_new_private_messages_create_receipts(self):
        update = {'update_id': 0, 'message': {'chat': {'type': 'private'}, 'text': 'private sample'}}
        telegram = reverse('telegram_channel_webhook')
        bale = reverse('bale_channel_webhook', kwargs={'secret': BALE_SECRET})
        self.assertEqual(self.client.post(telegram, update, content_type='application/json').status_code, 403)
        self.assertEqual(self.client.post(
            reverse('bale_channel_webhook', kwargs={'secret': 'invalid'}),
            update, content_type='application/json',
        ).status_code, 403)
        for _ in range(2):
            self.assertEqual(self.client.post(
                telegram, update, content_type='application/json',
                HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=TELEGRAM_SECRET,
            ).status_code, 200)
            self.assertEqual(self.client.post(bale, update, content_type='application/json').status_code, 200)

        update['message']['chat']['type'] = 'group'
        update['update_id'] = 1
        self.assertTrue(self.client.post(bale, update, content_type='application/json').json()['ignored'])
        self.assertEqual(ChannelMessageReceipt.objects.count(), 2)
        self.client.force_login(get_user_model().objects.create_user(username='owner'))
        response = self.client.get(reverse('agent_activity_snapshot'))
        by_channel = {channel['id']: channel for channel in response.json()['channels']}
        for provider in ['telegram', 'bale']:
            self.assertEqual(by_channel[provider]['count'], 1)
            self.assertEqual(by_channel[provider]['tone'], 'connected')
        self.assertNotContains(response, 'private sample')
        self.assertNotContains(response, BALE_SECRET)

    @patch('core.management.commands.channel_bot_webhook._provider_request')
    def test_registration_checks_existing_and_verifies_destination(self, provider_request):
        out = StringIO()
        provider_request.return_value = {'url': 'https://another.example.com/webhook'}
        with self.assertRaises(CommandError):
            call_command('channel_bot_webhook', 'telegram', '--register', stdout=out)
        self.assertEqual(provider_request.call_count, 1)

        url = 'https://staff.example.com' + reverse('telegram_channel_webhook')
        provider_request.reset_mock()
        provider_request.side_effect = [{'url': ''}, True, {'url': url}]
        call_command('channel_bot_webhook', 'telegram', '--register', stdout=out)
        self.assertEqual(provider_request.call_args_list[1].args[3], {
            'url': url, 'secret_token': TELEGRAM_SECRET, 'allowed_updates': ['message'],
        })
        self.assertIn('registered and verified', out.getvalue())
        self.assertNotIn(TELEGRAM_SECRET, out.getvalue())
