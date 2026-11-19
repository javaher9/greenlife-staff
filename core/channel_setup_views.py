import re
import secrets
from io import StringIO

from django.conf import settings
from django.contrib import messages
from django.core.management import CommandError, call_command
from django.db import transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_POST

from .channel_webhook_views import BotConnection, bot_connection, valid_token
from .credential_security import decrypt_secret, encrypt_secret
from .management.commands.channel_bot_webhook import API_HOSTS, _provider_request, webhook_target
from .models import ChannelBotSetup
from .views import credential_admin_required


class SetupError(Exception):
    pass


@sensitive_variables()
def configure(provider, supplied):
    managed = any(settings.CHANNEL_BOTS[provider])
    current = bot_connection(provider)
    if managed and not current:
        raise SetupError('تنظیمات توکن یا کلید وب‌هوک روی سرور ناقص است.')
    if managed and supplied:
        raise SetupError('توکن این ربات از تنظیمات سرور خوانده می‌شود.')
    if supplied and not valid_token(supplied):
        raise SetupError('قالب توکن درست نیست. توکن کامل ربات را وارد کنید.')
    token = supplied or (current.token if current else '')
    if not token:
        raise SetupError('برای شروع، توکن ربات را وارد کنید.')
    candidate = BotConnection(token, current.secret if current else secrets.token_urlsafe(32))
    if current and current.bot_id != candidate.bot_id:
        raise SetupError('این کانال از قبل به ربات دیگری اختصاص دارد.')
    identity = _provider_request(provider, token, 'getMe', {})
    if (not isinstance(identity, dict) or identity.get('id') != candidate.bot_id
            or not re.fullmatch(r'[A-Za-z0-9_]{1,80}', str(identity.get('username') or ''))):
        raise SetupError('هویت ربات از طرف سرویس تأیید نشد.')
    url, _ = webhook_target(provider, candidate)
    info = _provider_request(provider, token, 'getWebhookInfo', {})
    if not isinstance(info, dict) or not isinstance(info.get('url'), str):
        raise SetupError('وضعیت فعلی مسیر دریافت مشخص نشد.')
    if info['url'] and info['url'] != url:
        raise SetupError('این ربات پیام‌ها را به سامانهٔ دیگری می‌فرستد. برای گرین‌لایف یک ربات اختصاصی انتخاب کنید.')
    # Commit the receiving secret before the provider can send its first update.
    with transaction.atomic():
        row, _ = ChannelBotSetup.objects.select_for_update().get_or_create(provider=provider)
        if not managed:
            stored = decrypt_secret(row.token_cipher)
            if row.token_cipher and (not stored or stored.split(':', 1)[0] != token.split(':', 1)[0]):
                raise SetupError('تنظیمات ذخیره‌شده تغییر کرده است. صفحه را دوباره باز کنید.')
            if not row.secret_cipher:
                row.secret_cipher = encrypt_secret(candidate.secret)
            row.token_cipher = encrypt_secret(token)
        row.username = identity['username']
        row.save()
    call_command('channel_bot_webhook', provider, '--register', stdout=StringIO())
    ChannelBotSetup.objects.filter(pk=provider).update(verified_at=timezone.now())


@never_cache
@credential_admin_required
@require_POST
@sensitive_post_parameters('token')
@sensitive_variables()
def connect(request, provider):
    if provider not in API_HOSTS:
        raise Http404
    if not request.is_secure():
        return HttpResponseForbidden('اتصال امن HTTPS لازم است.')
    try:
        configure(provider, request.POST.get('token', '').strip())
    except SetupError as exc:
        messages.error(request, str(exc))
    except CommandError:
        messages.error(request, 'سرویس ربات اتصال را تأیید نکرد. توکن، دسترسی اینترنت سرور و نشانی عمومی دریافت را بررسی و دوباره تلاش کنید.')
    else:
        messages.success(request, 'مسیر دریافت تأیید شد. یک پیام خصوصی به ربات بدهید و وضعیت دریافت را در اتاق فرمان ببینید.')
    return redirect('agent_activity')
