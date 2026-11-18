import hmac
import json
import re
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import ChannelMessageReceipt


@dataclass(frozen=True)
class BotConnection:
    token: str
    secret: str

    @property
    def bot_id(self):
        return int(self.token.split(':', 1)[0])


def bot_connection(provider):
    token, secret = settings.CHANNEL_BOTS[provider]
    if (
        re.fullmatch(r'[1-9][0-9]{0,17}:[A-Za-z0-9_-]{15,180}', token)
        and re.fullmatch(r'[A-Za-z0-9_-]{32,128}', secret)
    ):
        return BotConnection(token, secret)
    return None


def _receive(request, provider, presented_secret):
    connection = bot_connection(provider)
    if not connection or not hmac.compare_digest(
        presented_secret.encode('utf-8'), connection.secret.encode('ascii')
    ):
        return JsonResponse({'ok': False}, status=403)

    try:
        raw = request.body
        if len(raw) > 256 * 1024:
            return JsonResponse({'ok': False}, status=413)
        update = json.loads(raw)
    except RequestDataTooBig:
        return JsonResponse({'ok': False}, status=413)
    except (UnicodeError, ValueError, RecursionError):
        return JsonResponse({'ok': False}, status=400)
    if not isinstance(update, dict):
        return JsonResponse({'ok': False}, status=400)
    update_id = update.get('update_id')
    if type(update_id) is not int or not 0 <= update_id < 2**63:
        return JsonResponse({'ok': False}, status=400)

    message = update.get('message')
    if not isinstance(message, dict):
        return JsonResponse({'ok': True, 'ignored': True})
    chat = message.get('chat')
    sender = message.get('from')
    if (
        not isinstance(chat, dict) or chat.get('type') != 'private'
        or isinstance(sender, dict) and sender.get('is_bot')
    ):
        return JsonResponse({'ok': True, 'ignored': True})

    _, created = ChannelMessageReceipt.objects.get_or_create(
        provider=provider,
        bot_id=connection.bot_id,
        update_id=update_id,
    )
    return JsonResponse({'ok': True, 'duplicate': not created})


@csrf_exempt
@require_POST
def telegram_channel_webhook(request):
    return _receive(request, 'telegram', request.headers.get('X-Telegram-Bot-Api-Secret-Token', ''))


@csrf_exempt
@require_POST
def bale_channel_webhook(request, secret):
    return _receive(request, 'bale', secret)
