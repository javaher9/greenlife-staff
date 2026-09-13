import os

from django.core.management.base import BaseCommand, CommandError

from core.telegram_agent import _telegram_api


class Command(BaseCommand):
    help = 'Register or delete the Green Life Telegram Bot webhook.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--url',
            default='',
            help='Public HTTPS webhook URL. Falls back to TELEGRAM_WEBHOOK_URL.',
        )
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Delete the current Telegram webhook instead of registering one.',
        )
        parser.add_argument(
            '--drop-pending',
            action='store_true',
            help='Drop queued Telegram updates while changing the webhook.',
        )

    def handle(self, *args, **options):
        token = os.getenv('TELEGRAM_BOT_TOKEN', '').strip()
        if not token:
            raise CommandError('TELEGRAM_BOT_TOKEN تنظیم نشده است.')

        if options['delete']:
            result = _telegram_api('deleteWebhook', {
                'drop_pending_updates': bool(options['drop_pending']),
            })
            if not result.get('ok'):
                raise CommandError(result.get('description') or 'حذف webhook ناموفق بود.')
            self.stdout.write(self.style.SUCCESS('Telegram webhook حذف شد.'))
            return

        webhook_url = (options['url'] or os.getenv('TELEGRAM_WEBHOOK_URL', '')).strip()
        if not webhook_url:
            raise CommandError('آدرس webhook را با --url یا TELEGRAM_WEBHOOK_URL مشخص کنید.')
        if not webhook_url.lower().startswith('https://'):
            raise CommandError('Telegram webhook باید یک آدرس عمومی HTTPS باشد.')

        secret = os.getenv('TELEGRAM_WEBHOOK_SECRET', '').strip()
        if not secret:
            raise CommandError('TELEGRAM_WEBHOOK_SECRET تنظیم نشده است.')

        result = _telegram_api('setWebhook', {
            'url': webhook_url,
            'secret_token': secret,
            'allowed_updates': ['message', 'callback_query'],
            'drop_pending_updates': bool(options['drop_pending']),
        })
        if not result.get('ok'):
            raise CommandError(result.get('description') or 'ثبت webhook ناموفق بود.')

        self.stdout.write(self.style.SUCCESS(f'Telegram webhook ثبت شد: {webhook_url}'))
