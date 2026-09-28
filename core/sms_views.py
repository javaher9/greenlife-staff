from django.contrib import messages
from django.core.validators import RegexValidator
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render

from .credential_security import encrypt_secret
from .forms import ApiServerSettingsForm, SmsTestForm
from .finance import fetch_crm_finance_payload
from .integration_api import ApiServerError
from .models import ApiServerSettings, AuditLog, SmsMessageLog, SmsAutomationRule, SmsScheduledMessage
from .sms_automation import OFFSET_LIMIT, validate_template
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


SMS_EVENT_GROUPS=(
    ('نوبت و مراجعه',('appointment_booked','appointment_reminder','appointment_changed','appointment_cancelled','patient_arrived')),
    ('مالی و پرداخت',('payment_approved','payment_due')),
    ('جلسات دستگاه و درمان',('device_session_booked','device_session_reminder','device_session_started','device_session_finished','treatment_followup')),
    ('کال‌سنتر',('lead_new','lead_overdue')),
    ('پرسنل و مدیریت',('staff_late','staff_task_due','internal_approval')),
)
# Only the appointment-booked event is connected to an existing event source.
# Enabling other rules saves configuration, but it cannot imply a live trigger.
SMS_CONNECTED_EVENTS={'appointment_booked','appointment_reminder'}


@_api_admin_required
@require_http_methods(['GET','POST'])
def sms_management(request):
    if request.method=='POST':
        event=(request.POST.get('event') or '').strip()
        if event not in dict(SmsAutomationRule.EVENT_CHOICES):
            messages.error(request,'رویداد پیامک معتبر نیست.')
            return redirect('sms_management')
        rule,_=SmsAutomationRule.objects.get_or_create(event=event)
        recipient=request.POST.get('recipient','patient')
        timing=request.POST.get('timing','immediate')
        offset_unit=request.POST.get('offset_unit','minutes')
        custom_number=(request.POST.get('custom_number') or '').strip()
        template=(request.POST.get('message_template') or '').strip()
        try:
            offset=int(request.POST.get('offset') or '0')
            if recipient not in dict(SmsAutomationRule.RECIPIENT_CHOICES):
                raise ValueError('گیرنده انتخاب‌شده معتبر نیست.')
            if timing not in dict(SmsAutomationRule.TIMING_CHOICES):
                raise ValueError('زمان‌بندی انتخاب‌شده معتبر نیست.')
            if offset_unit not in dict(SmsAutomationRule.UNIT_CHOICES):
                raise ValueError('واحد زمان معتبر نیست.')
            if offset<0 or offset*{'minutes':1,'hours':60,'days':1440}[offset_unit]>OFFSET_LIMIT:
                raise ValueError('فاصله ارسال نباید بیشتر از ۳۰ روز باشد.')
            if custom_number and (len(custom_number)!=11 or not custom_number.startswith('09') or not custom_number.isdigit()):
                raise ValueError('شماره اختصاصی باید ۱۱ رقم و با 09 شروع شود.')
            if recipient=='custom' and not custom_number:
                raise ValueError('برای گیرنده اختصاصی باید شماره موبایل وارد شود.')
            if not template and request.POST.get('is_enabled')=='on':
                raise ValueError('برای فعال‌سازی ابتدا متن پیامک را مشخص کنید.')
            validate_template(template)
        except ValueError as exc:
            messages.error(request,str(exc))
            return redirect('sms_management')
        rule.recipient=recipient
        rule.custom_number=custom_number
        rule.timing=timing
        rule.offset=offset
        rule.offset_unit=offset_unit
        rule.message_template=template
        # Disconnected events may be configured, but cannot be enabled or sent.
        requested_enabled=request.POST.get('is_enabled')=='on'
        rule.is_enabled=requested_enabled and event in SMS_CONNECTED_EVENTS
        rule.updated_by=request.user
        rule.save()
        AuditLog.objects.create(
            actor=request.user,action='sms_automation_rule_update',path=request.path,method='POST',
            object_type='SmsAutomationRule',object_id=str(rule.pk),
            summary=f'تنظیم رویداد پیامک: {rule.get_event_display()}',
            metadata={'event':event,'enabled':rule.is_enabled,'recipient':recipient,
                      'timing':timing,'offset':offset,'offset_unit':offset_unit},
            ip_address=request.META.get('REMOTE_ADDR') or None,
        )
        if requested_enabled and event not in SMS_CONNECTED_EVENTS:
            messages.warning(request,'تنظیمات ذخیره شد؛ این رویداد هنوز به اپ متصل نیست و ارسال آن غیرفعال می‌ماند.')
        else:
            messages.success(request,'تنظیمات پیامک ذخیره شد.')
        return redirect('sms_management')

    existing={rule.event:rule for rule in SmsAutomationRule.objects.all()}
    labels=dict(SmsAutomationRule.EVENT_CHOICES)
    groups=[{
        'title':title,
        'rules':[{
            'key':key,'title':labels[key],'rule':existing.get(key),
            'connected':key in SMS_CONNECTED_EVENTS,
        } for key in keys],
    } for title,keys in SMS_EVENT_GROUPS]
    latest=SmsScheduledMessage.objects.select_related('rule').order_by('-created_at')[:15]
    response=render(request,'core/sms_management.html',{
        'groups':groups,'recipient_choices':SmsAutomationRule.RECIPIENT_CHOICES,
        'timing_choices':SmsAutomationRule.TIMING_CHOICES,'unit_choices':SmsAutomationRule.UNIT_CHOICES,
        'pending_count':SmsScheduledMessage.objects.filter(status='pending').count(),
        'recent_queue':latest,'api_config':ApiServerSettings.load(),
    })
    response['Cache-Control']='no-store, private'
    return response
