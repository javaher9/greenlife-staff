from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from .credential_security import encrypt_secret
from .forms import ApiServerSettingsForm, SmsTestForm
from .finance import fetch_crm_finance_payload
from .integration_api import ApiServerError
from .models import ApiServerSettings, AuditLog, SmsMessageLog
from .sms import SmsGatewayError, send_sms
from .views import _is_executive_user


def _api_admin_required(view):
    @login_required
    def wrapper(request,*args,**kwargs):
        if not (request.user.is_superuser or _is_executive_user(request.user)):
            raise PermissionDenied('دسترسی تنظیمات API Server مجاز نیست.')
        return view(request,*args,**kwargs)
    return wrapper


@_api_admin_required
def api_server_settings(request):
    config=ApiServerSettings.load()
    action=request.POST.get('action') if request.method=='POST' else ''
    settings_form=ApiServerSettingsForm(
        request.POST if action=='save' else None,
        has_existing_key=bool(config.api_key_cipher),
        initial={
            'base_url':config.base_url,
            'is_enabled':config.is_enabled,
            'timeout_seconds':config.timeout_seconds,
            'appointment_confirmation_enabled':config.appointment_confirmation_enabled,
            'appointment_message_template':config.appointment_message_template,
        },
    )
    test_form=SmsTestForm(request.POST if action=='test' else None)

    if action=='save' and settings_form.is_valid():
        data=settings_form.cleaned_data
        config.base_url=data['base_url']
        if data['api_key']:
            config.api_key_cipher=encrypt_secret(data['api_key'])
        config.is_enabled=data['is_enabled']
        config.timeout_seconds=data['timeout_seconds']
        config.appointment_confirmation_enabled=data['appointment_confirmation_enabled']
        config.appointment_message_template=data['appointment_message_template']
        config.updated_by=request.user
        config.save()
        AuditLog.objects.create(
            actor=request.user,action='api_settings_update',path=request.path,method='POST',
            object_type='ApiServerSettings',object_id=str(config.pk),
            summary='تنظیمات API Server به‌روزرسانی شد.',
            metadata={
                'base_url':config.base_url,
                'is_enabled':config.is_enabled,
                'timeout_seconds':config.timeout_seconds,
                'appointment_confirmation_enabled':config.appointment_confirmation_enabled,
                'api_key_changed':bool(data['api_key']),
            },ip_address=request.META.get('REMOTE_ADDR') or None,
        )
        messages.success(request,'تنظیمات API Server با موفقیت ذخیره شد.')
        return redirect('api_server_settings')

    if action=='test' and test_form.is_valid():
        try:
            log,_payload=send_sms(
                test_form.cleaned_data['number'],test_form.cleaned_data['body'],
                purpose='test',created_by=request.user,allow_disabled=True,
            )
        except SmsGatewayError as exc:
            messages.error(request,f'ارسال آزمایشی ناموفق بود: {exc}')
        else:
            ids='، '.join(str(value) for value in log.provider_ids)
            suffix=f' شناسه: {ids}' if ids else ''
            messages.success(request,f'پیام توسط درگاه پذیرفته شد.{suffix}')
        return redirect('api_server_settings')

    crm_test=None
    if action=='test_crm':
        try:
            payload,rows=fetch_crm_finance_payload(allow_disabled=True)
            reported=payload.get('count')
            crm_test={'ok':True,'count':reported if reported is not None else len(rows)}
            messages.success(request,f'اتصال CRM موفق بود؛ {crm_test["count"]} ردیف دریافت شد.')
        except ApiServerError as exc:
            crm_test={'ok':False,'error':str(exc),'code':exc.code}
            messages.error(request,f'تست اتصال CRM ناموفق بود: {exc}')

    logs=SmsMessageLog.objects.select_related('created_by','appointment')[:25]
    response=render(request,'core/sms_settings.html',{
        'api_config':config,
        'settings_form':settings_form,
        'test_form':test_form,
        'sms_logs':logs,
        'crm_test':crm_test,
    })
    response['Cache-Control']='no-store, private'
    response['Pragma']='no-cache'
    return response
