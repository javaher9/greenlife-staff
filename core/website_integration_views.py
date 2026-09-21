import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .credential_security import decrypt_secret, encrypt_secret
from .models import AuditLog, WebsiteLeadIntegrationSettings
from .views import _is_executive_user


def _website_admin_required(view):
    @login_required
    def wrapper(request,*args,**kwargs):
        if not (request.user.is_superuser or _is_executive_user(request.user)):
            raise PermissionDenied('دسترسی تنظیمات اتصال سایت مجاز نیست.')
        return view(request,*args,**kwargs)
    return wrapper


@_website_admin_required
def website_lead_settings(request):
    config=WebsiteLeadIntegrationSettings.load()
    action=request.POST.get('action') if request.method=='POST' else ''

    if action=='rotate':
        token=secrets.token_urlsafe(36)
        config.api_key_cipher=encrypt_secret(token)
        config.is_enabled=True
        config.last_rotated_at=timezone.now()
        config.updated_by=request.user
        config.save()
        AuditLog.objects.create(
            actor=request.user,action='website_lead_key_rotate',path=request.path,method='POST',
            object_type='WebsiteLeadIntegrationSettings',object_id=str(config.pk),
            summary='کلید اتصال لید وب‌سایت تولید/چرخانده شد.',
            metadata={'is_enabled':True},ip_address=request.META.get('REMOTE_ADDR') or None,
        )
        messages.success(request,'کلید جدید Website Leads ساخته شد. مقدار جدید را در WordPress جایگزین کنید.')
        return redirect('website_lead_settings')

    if action=='toggle':
        config.is_enabled=request.POST.get('is_enabled')=='on'
        config.updated_by=request.user
        config.save(update_fields=['is_enabled','updated_by','updated_at'])
        AuditLog.objects.create(
            actor=request.user,action='website_lead_settings_update',path=request.path,method='POST',
            object_type='WebsiteLeadIntegrationSettings',object_id=str(config.pk),
            summary='وضعیت اتصال لید وب‌سایت تغییر کرد.',
            metadata={'is_enabled':config.is_enabled},ip_address=request.META.get('REMOTE_ADDR') or None,
        )
        messages.success(request,'وضعیت اتصال Website Leads ذخیره شد.')
        return redirect('website_lead_settings')

    api_key=decrypt_secret(config.api_key_cipher) if config.api_key_cipher else ''
    endpoint_url=request.build_absolute_uri(reverse('lead_ingest'))
    response=render(request,'core/website_lead_settings.html',{
        'website_config':config,
        'endpoint_url':endpoint_url,
        'api_key':api_key,
        'header_name':'X-Lead-Token',
        'bearer_header':'Authorization: Bearer <KEY>',
    })
    response['Cache-Control']='no-store, private'
    response['Pragma']='no-cache'
    return response
