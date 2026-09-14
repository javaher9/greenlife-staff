"""Shared server-side client for the Greenlife internal JSON API."""
import json
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .credential_security import decrypt_secret
from .models import ApiServerSettings


class ApiServerError(RuntimeError):
    def __init__(self,message,*,code='api_error',http_status=None,payload=None):
        super().__init__(message)
        self.code=code
        self.http_status=http_status
        self.payload=payload


def _decode_response(raw):
    text=(raw or b'').decode('utf-8',errors='replace')
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiServerError(
            'پاسخ API Server از نوع JSON نیست.',code='invalid_json',
            payload={'raw':text[:2000]},
        ) from exc


def call_api(path,body=None,*,allow_disabled=False):
    """POST JSON to one documented endpoint, reading settings on every call."""
    config=ApiServerSettings.load()
    if not config.is_configured:
        raise ApiServerError('تنظیمات API Server کامل نشده است.',code='not_configured')
    if not config.is_enabled and not allow_disabled:
        raise ApiServerError('API Server در تنظیمات غیرفعال است.',code='disabled')
    if not path.startswith('/') or path.startswith('/gl-api/'):
        raise ApiServerError('مسیر داخلی API معتبر نیست.',code='invalid_path')
    try:
        api_key=decrypt_secret(config.api_key_cipher)
    except Exception as exc:
        raise ApiServerError('X-API-Key ذخیره‌شده قابل خواندن نیست.',code='invalid_api_key_storage') from exc

    request=Request(
        f"{config.base_url.rstrip('/')}{path}",
        data=json.dumps(body or {},ensure_ascii=False).encode('utf-8'),
        headers={
            'Accept':'application/json',
            'Content-Type':'application/json',
            'X-API-Key':api_key,
        },
        method='POST',
    )
    try:
        with urlopen(request,timeout=config.timeout_seconds) as response:
            status=response.getcode()
            payload=_decode_response(response.read())
    except HTTPError as exc:
        raw=exc.read()
        try:
            payload=_decode_response(raw)
        except ApiServerError:
            payload={'raw':raw.decode('utf-8',errors='replace')[:2000]}
        code=payload.get('error','http_error') if isinstance(payload,dict) else 'http_error'
        raise ApiServerError(
            f'API Server خطای HTTP {exc.code} برگرداند.',
            code=code,http_status=exc.code,payload=payload,
        ) from exc
    except (URLError,socket.timeout,TimeoutError,OSError) as exc:
        raise ApiServerError(
            'ارتباط با API Server داخلی برقرار نشد.',
            code='transport_error',payload={'error':str(exc)[:500]},
        ) from exc

    if status<200 or status>=300:
        raise ApiServerError(
            f'API Server وضعیت HTTP {status} برگرداند.',
            code='http_error',http_status=status,payload=payload,
        )
    return status,payload
