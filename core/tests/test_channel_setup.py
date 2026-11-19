from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.channel_webhook_views import bot_connection
from core.models import ChannelBotSetup, ChannelMessageReceipt


@override_settings(CHANNEL_BOTS={'telegram': ('', ''), 'bale': ('', '')},
                   PUBLIC_BASE_URL='https://staff.example.com', EXECUTIVE_USERNAMES=['owner'])
class BotSetupTests(TestCase):
    token = '321:an_example_token_only_for_tests'
    identity = {'id': 321, 'username': 'GreenlifeExampleBot'}

    def setUp(self):
        self.owner = get_user_model().objects.create_user(username='owner')
        self.client.force_login(self.owner)
        self.url = reverse('agent_channel_connect', args=['telegram'])

    @patch('core.management.commands.channel_bot_webhook._provider_request')
    @patch('core.channel_setup_views._provider_request')
    def test_secure_setup_then_authenticated_delivery(self, preflight, register):
        preflight.side_effect = [self.identity, {'url': ''}]
        url = 'https://staff.example.com' + reverse('telegram_channel_webhook')
        register.side_effect = [{'url': ''}, True, {'url': url}]
        result = self.client.post(self.url, {'token': self.token}, secure=True, follow=True)
        self.assertContains(result, self.identity['username'])
        self.assertNotContains(result, self.token)
        saved = ChannelBotSetup.objects.get(pk='telegram')
        self.assertTrue(saved.verified_at)
        self.assertNotIn(self.token, saved.token_cipher)
        self.assertFalse(ChannelMessageReceipt.objects.exists())
        secret = bot_connection('telegram').secret
        body = {'update_id': 7, 'message': {'chat': {'type': 'private'}}}
        self.client.post(reverse('telegram_channel_webhook'), body, content_type='application/json',
                         HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN=secret)
        self.assertEqual(ChannelMessageReceipt.objects.count(), 1)
        self.assertEqual(register.call_args_list[1].args[3]['secret_token'], secret)

    @patch('core.channel_setup_views._provider_request')
    def test_other_destination_is_preserved(self, probe):
        probe.side_effect = [self.identity, {'url': 'https://other.example.net/hook'}]
        self.client.post(self.url, {'token': self.token}, secure=True)
        self.assertFalse(ChannelBotSetup.objects.exists())
        self.assertEqual([call.args[2] for call in probe.call_args_list], ['getMe','getWebhookInfo'])

    @patch('core.channel_setup_views._provider_request')
    def test_https_csrf_and_permissions(self, probe):
        self.assertEqual(self.client.post(self.url, {'token': self.token}).status_code, 403)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        blocked = guarded.post(self.url, {'token': self.token}, secure=True)
        self.assertIn(blocked.status_code, (302, 403))
        self.assertFalse(ChannelBotSetup.objects.exists())
        self.client.force_login(get_user_model().objects.create_user(username='staff'))
        self.assertEqual(self.client.post(self.url, {'token': self.token}, secure=True).status_code, 403)
        probe.assert_not_called()
