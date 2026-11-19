import json
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse

from core.channel_webhook_views import bot_connection


API_HOSTS = {'telegram': 'api.telegram.org', 'bale': 'tapi.bale.ai'}


def _provider_request(provider, token, method, parameters):
    request = Request(
        f'https://{API_HOSTS[provider]}/bot{token}/{method}',
        data=json.dumps(parameters).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urlopen(request, timeout=12) as response:
            result = json.load(response)
    except (URLError, OSError, ValueError):
        raise CommandError(f'{provider} {method} could not be verified.') from None
    if not isinstance(result, dict) or result.get('ok') is not True:
        raise CommandError(f'{provider} rejected {method}.')
    return result.get('result')


def webhook_target(provider, connection):
    base = settings.PUBLIC_BASE_URL
    origin = urlsplit(base)
    if origin.scheme != 'https' or not origin.hostname or origin.username or origin.path or origin.query or origin.fragment:
        raise CommandError('PUBLIC_BASE_URL must be a public HTTPS origin.')

    parameters = {}
    if provider == 'telegram':
        path = reverse('telegram_channel_webhook')
        parameters.update(secret_token=connection.secret, allowed_updates=['message'])
    else:
        path = reverse('bale_channel_webhook', kwargs={'secret': connection.secret})
    url = base + path
    return url, parameters


class Command(BaseCommand):
    help = 'Inspect or register the GreenLife webhook for a configured channel bot.'

    def add_arguments(self, parser):
        parser.add_argument('provider', choices=API_HOSTS)
        parser.add_argument('--register', action='store_true')
        parser.add_argument('--replace', action='store_true', help='Allow replacing a different existing webhook.')

    def handle(self, provider, register, replace, **options):
        connection = bot_connection(provider)
        if connection is None:
            raise CommandError('Configure the bot token and a separate random webhook secret first.')
        url, parameters = webhook_target(provider, connection)
        info = _provider_request(provider, connection.token, 'getWebhookInfo', {})
        if not isinstance(info, dict) or not isinstance(info.get('url'), str):
            raise CommandError('The provider returned unrecognized webhook information.')
        existing = info['url']
        if not register:
            status = 'registered here' if existing == url else 'registered elsewhere' if existing else 'not registered'
            self.stdout.write(f'{provider} webhook: {status}')
            return

        if existing and existing != url and not replace:
            raise CommandError('This bot has a different webhook. Use a dedicated bot or explicitly replace it.')
        result = _provider_request(provider, connection.token, 'setWebhook', {'url': url, **parameters})
        if result is not True:
            raise CommandError('Webhook registration was not confirmed.')
        verified = _provider_request(provider, connection.token, 'getWebhookInfo', {})
        if not isinstance(verified, dict) or verified.get('url') != url:
            raise CommandError('Webhook registration was not verified by the provider.')
        self.stdout.write(self.style.SUCCESS(f'{provider} webhook registered and verified.'))
