"""Limited direct and group SMS composer, separated from gateway administration."""
import re
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import ApiServerSettings, PatientProfile, ReferralLead, SmsMessageLog
from .sms import SmsGatewayError, send_sms


def _is_allowed(user):
    profile=getattr(user,'profile',None)
    return bool(user.is_active and (user.is_superuser or
        (profile and profile.is_active and profile.can_send_marketing_sms)))


def _iran_mobile(number):
    raw=re.sub(r'[^0-9]','',str(number or ''))
    if raw.startswith('0098'):
        raw='0'+raw[4:]
    elif raw.startswith('98') and len(raw)==12:
        raw='0'+raw[2:]
    return raw if len(raw)==11 and raw.startswith('09') and raw.isdigit() else ''


@login_required
@require_http_methods(['GET','POST'])
def marketing_sms_compose(request):
    if not _is_allowed(request.user):
        raise PermissionDenied('اجازه ارسال پیامک برای این حساب فعال نیست.')

    q=(request.GET.get('q') or '').strip()[:80]
    source=(request.GET.get('source') or 'leads').strip()
    if source not in ('leads','patients'):
        source='leads'

    # Search is read-only, capped, and scoped to the active Iran workspace.
    if source=='leads':
        queryset=ReferralLead.objects.filter(country__code='IR')
        if q:
            queryset=queryset.filter(Q(full_name__icontains=q)|Q(phone__icontains=q))
        results=list(queryset.order_by('-id').values('id','full_name','phone')[:100])
    else:
        queryset=PatientProfile.objects.all()
        if q:
            queryset=queryset.filter(Q(full_name__icontains=q)|Q(phone__icontains=q))
        results=list(queryset.order_by('-id').values('id','full_name','phone')[:100])

    if request.method=='POST':
        body=(request.POST.get('body') or '').strip()
        mode=request.POST.get('mode')
        numbers=[]
        if not body or len(body)>600:
            messages.error(request,'متن پیامک باید بین ۱ تا ۶۰۰ نویسه باشد.')
            return redirect('marketing_sms_compose')
        if mode=='manual':
            numbers=[_iran_mobile(n) for n in re.split(r'[,;،\\n]+',request.POST.get('numbers','')) if n.strip()]
        elif mode=='selected':
            selected=request.POST.getlist('selected_ids')[:26]
            ids=[int(x) for x in selected if x.isdecimal()]
            chosen_source=request.POST.get('source')
            if len(ids)>25 or len(ids)!=len(selected) or chosen_source not in ('leads','patients'):
                messages.error(request,'حداکثر ۲۵ مخاطب معتبر را انتخاب کنید.')
                return redirect('marketing_sms_compose')
            if chosen_source=='leads':
                numbers=list(ReferralLead.objects.filter(pk__in=ids,country__code='IR').values_list('phone',flat=True))
            else:
                numbers=list(PatientProfile.objects.filter(pk__in=ids).values_list('phone',flat=True))
            numbers=[_iran_mobile(n) for n in numbers]
        else:
            messages.error(request,'نوع ارسال معتبر نیست.')
            return redirect('marketing_sms_compose')

        if any(not number for number in numbers):
            messages.error(request,'یک یا چند شماره ایرانی معتبر نیست.')
            return redirect('marketing_sms_compose')
        numbers=list(dict.fromkeys(numbers))
        if not numbers or len(numbers)>25:
            messages.error(request,'بین ۱ تا ۲۵ شماره برای هر ارسال انتخاب کنید.')
            return redirect('marketing_sms_compose')

        daily=SmsMessageLog.objects.filter(
            created_by=request.user,created_at__gte=timezone.now()-timedelta(hours=24),
        ).count()
        if daily+len(numbers)>100:
            messages.error(request,'سقف ارسال این حساب ۱۰۰ پیامک در ۲۴ ساعت است.')
            return redirect('marketing_sms_compose')

        if not (ApiServerSettings.load().is_enabled and ApiServerSettings.load().is_configured):
            messages.error(request,'درگاه REST API پیامک فعال نیست.')
            return redirect('marketing_sms_compose')

        accepted=0
        failed=0
        for number in numbers:
            try:
                send_sms(number,body,created_by=request.user,purpose='manual')
                accepted+=1
            except (SmsGatewayError,Exception):
                failed+=1
        if accepted:
            messages.success(request,f'{accepted} پیامک توسط درگاه پذیرفته شد؛ تحویل نهایی وابسته به اپراتور است.')
        if failed:
            messages.warning(request,f'ارسال {failed} پیامک ناموفق بود. وضعیت را به مدیر اطلاع دهید.')
        return redirect('marketing_sms_compose')

    recent=SmsMessageLog.objects.filter(created_by=request.user).order_by('-created_at')[:15]
    return render(request,'core/marketing_sms_compose.html',{
        'results':results,'q':q,'source':source,'recent':recent,
    })
