import hashlib
import hmac
import json
import secrets
from datetime import timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_http_methods

from .credential_security import decrypt_secret, encrypt_secret
from .models import InstagramIntegrationSettings, InstagramWebhookEvent
from .views import _is_executive_user


# OAuth proxy rewrite guard deployed with squashed base.
INSTAGRAM_OAUTH_URL='https://www.instagram.com/oauth/authorize'
INSTAGRAM_TOKEN_URL='https://api.instagram.com/oauth/access_token'
INSTAGRAM_GRAPH_BASE='https://graph.instagram.com'
INSTAGRAM_BRIDGE_BASE='https://instagram-bridge-production-e356.up.railway.app'
# Railway bridge is the production Meta egress path.
INSTAGRAM_SCOPES=(
    'instagram_business_basic',
    'instagram_business_manage_messages',
    'instagram_business_manage_comments',
)


def _executive_required(view):
    @login_required(login_url='/login/')
    def wrapper(request,*args,**kwargs):
        if not (request.user.is_superuser or _is_executive_user(request.user)):
            raise PermissionDenied('دسترسی تنظیمات Instagram مجاز نیست.')
        return view(request,*args,**kwargs)
    return wrapper


def _public_base_url(request):
    configured=(getattr(settings,'PUBLIC_BASE_URL','') or '').strip().rstrip('/')
    if configured:
        return configured
    return 'https://staff.greenlifeclinics.com'


def _redirect_uri(request):
    return _public_base_url(request)+reverse('instagram_oauth_callback')


def _webhook_uri(request):
    return _public_base_url(request)+reverse('instagram_webhook')


def _post_form(url,data,timeout=20):
    body=urlencode(data).encode('utf-8')
    req=Request(url,data=body,headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
    with urlopen(req,timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8') or '{}')


def _post_json(url,data,timeout=25):
    body=json.dumps(data).encode('utf-8')
    req=Request(url,data=body,headers={'Content-Type':'application/json','Accept':'application/json'},method='POST')
    with urlopen(req,timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8') or '{}')


def _get_json(url,params,timeout=20):
    full=url+'?'+urlencode(params)
    req=Request(full,headers={'Accept':'application/json'})
    with urlopen(req,timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8') or '{}')


@_executive_required
@require_http_methods(['GET','POST'])
def instagram_settings(request):
    config=InstagramIntegrationSettings.load()
    if request.method=='POST':
        app_id=(request.POST.get('app_id') or '').strip()
        app_secret=(request.POST.get('app_secret') or '').strip()
        if not app_id.isdigit():
            messages.error(request,'App ID باید فقط شناسه عددی Meta باشد؛ آدرس سایت یا URL وارد نکنید.')
            return redirect('instagram_settings')
        config.app_id=app_id
        if app_secret:
            config.app_secret_cipher=encrypt_secret(app_secret)
        if not config.verify_token_cipher:
            config.verify_token_cipher=encrypt_secret(secrets.token_urlsafe(32))
        config.is_enabled=request.POST.get('is_enabled')=='on'
        config.updated_by=request.user
        config.save()
        messages.success(request,'تنظیمات Instagram با امنیت ذخیره شد.')
        return redirect('instagram_settings')

    direct_auth_url=''
    if config.is_configured:
        state=secrets.token_urlsafe(32)
        request.session['instagram_oauth_state']=state
        request.session['instagram_oauth_started_at']=timezone.now().isoformat()
        direct_auth_url=INSTAGRAM_OAUTH_URL+'?'+urlencode({
            'client_id':config.app_id,
            'redirect_uri':_redirect_uri(request),
            'response_type':'code',
            'scope':','.join(INSTAGRAM_SCOPES),
            'state':state,
            'force_reauth':'true',
        })

    response=render(request,'core/instagram_settings.html',{
        'config':config,
        'redirect_uri':_redirect_uri(request),
        'webhook_uri':INSTAGRAM_BRIDGE_BASE+'/meta/webhook',
        'direct_auth_url':direct_auth_url,
        'has_app_secret':bool(config.app_secret_cipher),
        'has_verify_token':bool(config.verify_token_cipher),
    })
    response['Cache-Control']='no-store, private'
    return response


@_executive_required
@require_GET
def instagram_oauth_start(request):
    config=InstagramIntegrationSettings.load()
    if not config.is_configured:
        messages.error(request,'ابتدا App ID و App Secret را در تنظیمات Instagram ذخیره کنید.')
        return redirect('instagram_settings')

    state=secrets.token_urlsafe(32)
    request.session['instagram_oauth_state']=state
    request.session['instagram_oauth_started_at']=timezone.now().isoformat()
    query={
        'client_id':config.app_id,
        'redirect_uri':_redirect_uri(request),
        'response_type':'code',
        'scope':','.join(INSTAGRAM_SCOPES),
        'state':state,
        'force_reauth':'true',
    }
    auth_url=INSTAGRAM_OAUTH_URL+'?'+urlencode(query)
    # Some reverse-proxy stacks rewrite external Location headers. Return a tiny
    # navigation document so the browser itself performs the absolute jump to Instagram.
    safe_url=escape(auth_url, quote=True)
    script_url=json.dumps(auth_url)
    return HttpResponse(
        '<!doctype html><html><head><meta charset="utf-8">'
        f'<meta http-equiv="refresh" content="0;url={safe_url}">'
        '<title>Instagram Login</title></head><body>'
        f'<p><a href="{safe_url}" rel="noreferrer">Continue to Instagram</a></p>'
        f'<script>window.location.replace({script_url});</script>'
        '</body></html>'
    )


@require_GET
def instagram_oauth_callback(request):
    config=InstagramIntegrationSettings.load()
    expected=request.session.pop('instagram_oauth_state',None)
    state=request.GET.get('state')
    if not expected or not state or not hmac.compare_digest(str(expected),str(state)):
        return HttpResponse('Instagram OAuth state validation failed.',status=400)

    if request.GET.get('error'):
        detail=request.GET.get('error_description') or request.GET.get('error_reason') or request.GET.get('error')
        return HttpResponse(f'Instagram authorization was not completed: {detail}',status=400)

    code=(request.GET.get('code') or '').strip()
    if not code:
        return HttpResponse('Instagram authorization code is missing.',status=400)

    app_secret=decrypt_secret(config.app_secret_cipher)
    if not config.app_id or not app_secret:
        return HttpResponse('Instagram app credentials are not configured.',status=503)

    try:
        bridge=_post_json(INSTAGRAM_BRIDGE_BASE+'/meta/oauth-complete',{
            'app_id':config.app_id,
            'app_secret':app_secret,
            'redirect_uri':_redirect_uri(request),
            'code':code,
        })
        if not bridge.get('ok'):
            raise ValueError('Instagram bridge did not complete OAuth.')

        token=str(bridge.get('access_token') or '')
        user_id=str(bridge.get('user_id') or '')
        username=str(bridge.get('username') or '')
        expires_in=int(bridge.get('expires_in') or 0)
        if not token:
            raise ValueError('Instagram bridge did not return an access token.')

        config.access_token_cipher=encrypt_secret(token)
        config.instagram_user_id=user_id
        config.username=username
        config.token_expires_at=timezone.now()+timedelta(seconds=expires_in) if expires_in else None
        config.connected_at=timezone.now()
        config.is_enabled=True
        config.save(update_fields=[
            'access_token_cipher','instagram_user_id','username','token_expires_at',
            'connected_at','is_enabled','updated_at',
        ])
    except HTTPError as exc:
        detail=''
        try:
            raw=exc.read().decode('utf-8','replace')
            parsed=json.loads(raw or '{}')
            error=parsed.get('error') if isinstance(parsed,dict) else None
            if isinstance(error,dict):
                detail=str(error.get('message') or error.get('error_user_msg') or error)
                code=error.get('code')
                error_type=error.get('type')
                extras=[]
                if error_type:
                    extras.append(str(error_type))
                if code is not None:
                    extras.append(f'code {code}')
                if extras:
                    detail += ' ('+', '.join(extras)+')'
            elif isinstance(parsed,dict):
                detail=str(parsed.get('error_message') or parsed.get('message') or raw)
            else:
                detail=raw
        except Exception:
            detail=str(exc)
        return HttpResponse(
            'Instagram token exchange failed: '+(detail or f'HTTP {getattr(exc,"code","error")}'),
            status=502,
        )
    except URLError as exc:
        reason=getattr(exc,'reason',None)
        detail=repr(reason) if reason is not None else repr(exc)
        return HttpResponse(
            f'Instagram token exchange failed [network]: {detail}',
            status=502,
        )
    except TimeoutError as exc:
        return HttpResponse(
            f'Instagram token exchange failed [timeout]: {repr(exc)}',
            status=502,
        )
    except (ValueError,KeyError,json.JSONDecodeError) as exc:
        return HttpResponse(
            f'Instagram token exchange failed [response]: {repr(exc)}',
            status=502,
        )
    except Exception as exc:
        return HttpResponse(
            f'Instagram token exchange failed [{type(exc).__name__}]: {repr(exc)}',
            status=502,
        )

    if request.user.is_authenticated:
        messages.success(request,f'Instagram @{config.username or "account"} با موفقیت متصل شد.')
        return redirect('instagram_settings')
    return HttpResponse('Instagram connected successfully. You may close this page.')


@csrf_exempt
@require_http_methods(['GET','POST'])
def instagram_webhook(request):
    config=InstagramIntegrationSettings.load()

    if request.method=='GET':
        mode=request.GET.get('hub.mode')
        supplied=request.GET.get('hub.verify_token') or ''
        challenge=request.GET.get('hub.challenge') or ''
        expected=decrypt_secret(config.verify_token_cipher)
        if mode=='subscribe' and expected and hmac.compare_digest(supplied,expected):
            return HttpResponse(challenge,content_type='text/plain')
        return HttpResponse('Forbidden',status=403)

    raw=request.body or b''
    app_secret=decrypt_secret(config.app_secret_cipher)
    signature=request.headers.get('X-Hub-Signature-256','')
    if app_secret:
        expected_sig='sha256='+hmac.new(app_secret.encode('utf-8'),raw,hashlib.sha256).hexdigest()
        if not signature or not hmac.compare_digest(signature,expected_sig):
            return JsonResponse({'ok':False,'error':'invalid_signature'},status=403)

    try:
        payload=json.loads(raw.decode('utf-8') or '{}')
    except (UnicodeDecodeError,json.JSONDecodeError):
        return JsonResponse({'ok':False,'error':'invalid_json'},status=400)

    digest=hashlib.sha256(raw).hexdigest()
    event,created=InstagramWebhookEvent.objects.get_or_create(
        event_hash=digest,
        defaults={'payload':payload,'status':'received'},
    )
    return JsonResponse({'ok':True,'event_id':event.id,'duplicate':not created},status=200)
