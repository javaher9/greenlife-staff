from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET

from .models import AuditLog, ReferralLead, ReferralProfile, normalize_lead_phone
from .lead_routing import assign_social_lead
from .views import _is_executive_user


CATEGORIES={
    'consultation':'لیدهای درخواست مشاوره',
    'campaign':'لیدهای پیامک تبلیغاتی',
    'cancel':'درخواست لغو',
    'other':'غیره',
}


def classify_sms_reply(text):
    value=' '.join(str(text or '').split())
    if value=='20':
        return 'consultation',True
    if value in {'5','6','7','8','9'}:
        return 'campaign',True
    if value=='11':
        return 'cancel',False
    return 'other',False


def _sms_source():
    user,_=User.objects.get_or_create(
        username='sms-center-source',
        defaults={'first_name':'SMS Center','last_name':'GreenLife','is_active':False},
    )
    if user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=['password'])
    profile,_=ReferralProfile.objects.get_or_create(
        user=user,
        defaults={'referral_code':'GLSMSCTR','is_active':False},
    )
    return profile


@csrf_exempt
@require_GET
def sms_center_callback(request):
    phone=normalize_lead_phone(request.GET.get('from',''))
    destination=(request.GET.get('to') or '').strip()[:80]
    body=(request.GET.get('text') or '').strip()[:1600]
    message_time=(request.GET.get('time') or '').strip()[:80]
    category,is_lead=classify_sms_reply(body)
    lead=None
    if is_lead and phone:
        lead=ReferralLead.recent_duplicate_for_phone(phone)
        if lead is None:
            lead=ReferralLead.objects.create(
                referrer=_sms_source(),
                full_name=f'پاسخ پیامکی {phone}',
                phone=phone,
                interested_service='مشاوره لاغری' if category=='consultation' else 'کمپین پیامکی',
                source='link',
                source_url=request.build_absolute_uri(),
                notes=f'[channel:sms] [sms_category:{category}] پاسخ مشتری: {body}',
            )
            assign_social_lead(
                lead,
                group_name='پیامک - درخواست مشاوره' if category=='consultation' else 'پیامک - تبلیغاتی',
                notification_title='لید جدید پیامکی',
            )
    AuditLog.objects.create(
        actor=None,action='sms_center_reply',path=request.path,method='GET',
        object_type='ReferralLead' if lead else 'SmsReply',
        object_id=str(lead.pk) if lead else '',
        summary=f'{CATEGORIES[category]}: {phone or "بدون شماره"}',
        metadata={
            'from':phone,'to':destination,'text':body,'time':message_time,
            'category':category,'category_label':CATEGORIES[category],
            'lead_id':lead.pk if lead else None,
            'assigned_to':lead.assigned_to_id if lead else None,
        },
        ip_address=request.META.get('REMOTE_ADDR') or None,
    )
    return JsonResponse({'ok':True})


def _admin_required(request):
    return request.user.is_superuser or _is_executive_user(request.user) or getattr(getattr(request.user,'profile',None),'role','') in ('admin','manager','internal_manager')


@login_required
def sms_leads(request):
    if not _admin_required(request):
        raise PermissionDenied('دسترسی لیدهای پیامکی مجاز نیست.')
    selected=(request.GET.get('category') or 'all').strip()
    rows=list(AuditLog.objects.filter(action='sms_center_reply').order_by('-created_at')[:500])
    if selected in CATEGORIES:
        rows=[x for x in rows if (x.metadata or {}).get('category')==selected]
    counts={'all':len(rows) if selected=='all' else AuditLog.objects.filter(action='sms_center_reply').count()}
    all_rows=list(AuditLog.objects.filter(action='sms_center_reply').order_by('-created_at')[:1000])
    for key in CATEGORIES:
        counts[key]=sum(1 for x in all_rows if (x.metadata or {}).get('category')==key)
    lead_ids=[(x.metadata or {}).get('lead_id') for x in rows if (x.metadata or {}).get('lead_id')]
    leads={x.pk:x for x in ReferralLead.objects.filter(pk__in=lead_ids).select_related('assigned_to__user','group')}
    items=[]
    for row in rows:
        meta=row.metadata or {}
        items.append({'row':row,'meta':meta,'lead':leads.get(meta.get('lead_id'))})
    return render(request,'core/sms_leads.html',{
        'items':items,'counts':counts,'categories':CATEGORIES,'selected':selected,
    })


def callback_url(request):
    base=request.build_absolute_uri(reverse('sms_center_callback'))
    return base+'?from=%%address%%&to=%%dest%%&text=%%body%%&time=%%time%%'
