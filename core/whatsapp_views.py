import hashlib
import hmac
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q
from django.db.models.functions import TruncDate
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from datetime import timedelta
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from .models import Branch, EmployeeProfile, WhatsAppMessage, WhatsAppNumber
from .views import _is_executive_user


WHATSAPP_BRIDGE_EVENT_KEY_SHA256='7660ee37ec59818e06cac353a3f72a46a2f93c3213ad1196c34e422e6ac3b037'


def _bridge_event_authorized(request):
    supplied=(request.headers.get('X-WhatsApp-Bridge-Key') or '').strip()
    if not supplied:
        return False
    digest=hashlib.sha256(supplied.encode('utf-8')).hexdigest()
    return hmac.compare_digest(digest,WHATSAPP_BRIDGE_EVENT_KEY_SHA256)


def _phone_digits(value):
    return ''.join(ch for ch in str(value or '') if ch.isdigit())


def _match_whatsapp_number(phone_number_id='',display_phone_number=''):
    phone_number_id=str(phone_number_id or '').strip()
    if phone_number_id:
        match=WhatsAppNumber.objects.filter(phone_number_id=phone_number_id).first()
        if match:
            return match

    digits=_phone_digits(display_phone_number)
    if not digits:
        return None
    for item in WhatsAppNumber.objects.all().only('id','phone_number','phone_number_id'):
        if _phone_digits(item.phone_number)==digits:
            if phone_number_id and not item.phone_number_id:
                item.phone_number_id=phone_number_id
                item.save(update_fields=['phone_number_id','updated_at'])
            return item
    return None


@csrf_exempt
@require_POST
def whatsapp_bridge_event(request):
    if not _bridge_event_authorized(request):
        return JsonResponse({'ok':False,'error':'unauthorized'},status=401)

    try:
        payload=json.loads(request.body.decode('utf-8') or '{}')
    except (UnicodeDecodeError,json.JSONDecodeError):
        return JsonResponse({'ok':False,'error':'invalid_json'},status=400)

    if not isinstance(payload,dict):
        return JsonResponse({'ok':False,'error':'invalid_payload'},status=400)

    event_type=str(payload.get('event_type') or '').strip().lower()
    phone_number_id=str(payload.get('phone_number_id') or '').strip()
    display_phone_number=str(payload.get('display_phone_number') or '').strip()
    number=_match_whatsapp_number(phone_number_id,display_phone_number)

    if not number:
        return JsonResponse({
            'ok':False,
            'error':'whatsapp_number_not_found',
            'phone_number_id':phone_number_id or None,
        },status=404)

    now=timezone.now()
    number_updates=['last_webhook_at','updated_at']
    number.last_webhook_at=now
    if number.connection_status!='connected':
        number.connection_status='connected'
        number_updates.append('connection_status')
    if display_phone_number and not number.display_name:
        number.display_name=display_phone_number[:120]
        number_updates.append('display_name')
    number.save(update_fields=list(dict.fromkeys(number_updates)))

    if event_type in ('message','outbound_message'):
        message_id=str(payload.get('message_id') or '').strip() or None
        direction='outbound' if event_type=='outbound_message' else 'inbound'
        outbound_mode=str(payload.get('outbound_mode') or '').strip()
        if outbound_mode not in dict(WhatsAppMessage.OUTBOUND_MODE_CHOICES):
            outbound_mode=''
        status=str(payload.get('status') or '').strip()
        valid_statuses=dict(WhatsAppMessage.STATUS_CHOICES)
        if status not in valid_statuses:
            status='sent' if direction=='outbound' else 'received'

        defaults={
            'whatsapp_number':number,
            'contact_phone':str(payload.get('contact_phone') or '')[:32],
            'contact_name':str(payload.get('contact_name') or '')[:140],
            'direction':direction,
            'outbound_mode':outbound_mode,
            'message_type':str(payload.get('message_type') or 'text')[:32],
            'body':str(payload.get('body') or ''),
            'status':status,
            'is_ai':outbound_mode=='ai',
            'is_read_by_staff':direction=='outbound',
            'metadata':payload.get('metadata') if isinstance(payload.get('metadata'),dict) else {},
        }

        if message_id:
            message,created=WhatsAppMessage.objects.update_or_create(
                wa_message_id=message_id,
                defaults=defaults,
            )
        else:
            message=WhatsAppMessage.objects.create(wa_message_id=None,**defaults)
            created=True

        return JsonResponse({
            'ok':True,
            'event_type':event_type,
            'message_id':message.id,
            'created':created,
            'whatsapp_number_id':number.id,
        },status=201 if created else 200)

    if event_type=='status':
        message_id=str(payload.get('message_id') or '').strip()
        status=str(payload.get('status') or '').strip()
        valid_statuses=dict(WhatsAppMessage.STATUS_CHOICES)
        if not message_id or status not in valid_statuses:
            return JsonResponse({'ok':False,'error':'invalid_status_event'},status=400)

        message=WhatsAppMessage.objects.filter(
            wa_message_id=message_id,
            whatsapp_number=number,
        ).first()
        if not message:
            return JsonResponse({
                'ok':True,
                'event_type':'status',
                'updated':False,
                'reason':'message_not_found_yet',
            })

        fields=['status']
        message.status=status
        if status=='delivered':
            message.delivered_at=now
            fields.append('delivered_at')
        elif status=='read':
            message.read_at=now
            fields.append('read_at')
            if not message.delivered_at:
                message.delivered_at=now
                fields.append('delivered_at')
        message.save(update_fields=list(dict.fromkeys(fields)))
        return JsonResponse({'ok':True,'event_type':'status','updated':True})

    return JsonResponse({'ok':False,'error':'unsupported_event_type'},status=400)


def _whatsapp_admin_required(view):
    @login_required(login_url='/login/')
    def wrapper(request,*args,**kwargs):
        role=getattr(getattr(request.user,'profile',None),'role','')
        if not (request.user.is_superuser or _is_executive_user(request.user) or role=='admin'):
            raise PermissionDenied('دسترسی مدیریت واتساپ مجاز نیست.')
        return view(request,*args,**kwargs)
    return wrapper


@_whatsapp_admin_required
@require_http_methods(['GET','POST'])
def whatsapp_hub(request):
    if request.method=='POST':
        action=(request.POST.get('action') or '').strip()

        if action=='add_number':
            label=(request.POST.get('label') or '').strip()
            phone=(request.POST.get('phone_number') or '').strip()
            phone_number_id=(request.POST.get('phone_number_id') or '').strip() or None
            business_account_id=(request.POST.get('business_account_id') or '').strip()
            branch_id=(request.POST.get('branch_id') or '').strip()
            responsible_id=(request.POST.get('responsible_id') or '').strip()
            number_type=(request.POST.get('number_type') or 'branch').strip()

            if number_type not in dict(WhatsAppNumber.TYPE_CHOICES):
                number_type='other'

            if not label or not phone:
                messages.error(request,'نام شماره و خود شماره واتساپ الزامی است.')
                return redirect('whatsapp_hub')

            if phone_number_id and WhatsAppNumber.objects.filter(phone_number_id=phone_number_id).exists():
                messages.error(request,'این Phone Number ID قبلاً ثبت شده است.')
                return redirect('whatsapp_hub')

            branch=None
            if branch_id:
                branch=Branch.objects.filter(pk=branch_id,is_active=True).first()

            responsible=None
            if responsible_id:
                responsible=EmployeeProfile.objects.filter(
                    pk=responsible_id,is_active=True,user__is_active=True,
                ).select_related('user').first()

            WhatsAppNumber.objects.create(
                label=label[:100],
                phone_number=phone[:32],
                phone_number_id=phone_number_id,
                business_account_id=business_account_id[:120],
                number_type=number_type,
                branch=branch,
                responsible=responsible,
                connection_status='pending',
                is_active=True,
            )
            messages.success(request,'شماره واتساپ اضافه شد و برای اتصال Meta آماده است.')
            return redirect('whatsapp_hub')

        if action=='edit_number':
            number=get_object_or_404(WhatsAppNumber,pk=request.POST.get('number_id'))
            label=(request.POST.get('label') or '').strip()
            phone=(request.POST.get('phone_number') or '').strip()
            phone_number_id=(request.POST.get('phone_number_id') or '').strip() or None
            business_account_id=(request.POST.get('business_account_id') or '').strip()
            branch_id=(request.POST.get('branch_id') or '').strip()
            responsible_id=(request.POST.get('responsible_id') or '').strip()
            number_type=(request.POST.get('number_type') or 'branch').strip()

            if not label or not phone:
                messages.error(request,'نام شماره و خود شماره واتساپ الزامی است.')
                return redirect('whatsapp_hub')

            if number_type not in dict(WhatsAppNumber.TYPE_CHOICES):
                number_type='other'

            if phone_number_id and WhatsAppNumber.objects.filter(
                phone_number_id=phone_number_id,
            ).exclude(pk=number.pk).exists():
                messages.error(request,'این Phone Number ID قبلاً برای شماره دیگری ثبت شده است.')
                return redirect('whatsapp_hub')

            branch=None
            if branch_id:
                branch=Branch.objects.filter(pk=branch_id,is_active=True).first()

            responsible=None
            if responsible_id:
                responsible=EmployeeProfile.objects.filter(
                    pk=responsible_id,is_active=True,user__is_active=True,
                ).select_related('user').first()

            technical_changed=(
                number.phone_number != phone[:32]
                or number.phone_number_id != phone_number_id
                or number.business_account_id != business_account_id[:120]
            )

            number.label=label[:100]
            number.phone_number=phone[:32]
            number.phone_number_id=phone_number_id
            number.business_account_id=business_account_id[:120]
            number.number_type=number_type
            number.branch=branch
            number.responsible=responsible
            if technical_changed and number.connection_status=='connected':
                number.connection_status='pending'
                number.last_error=''
                messages.warning(
                    request,
                    'اطلاعات فنی شماره تغییر کرد؛ وضعیت اتصال روی «در انتظار اتصال» قرار گرفت.',
                )
            number.save()
            messages.success(request,'اطلاعات شماره واتساپ ویرایش شد.')
            return redirect('whatsapp_hub')

        if action=='delete_number':
            number=get_object_or_404(WhatsAppNumber,pk=request.POST.get('number_id'))
            has_history=number.messages.exists()
            label=number.label
            if has_history:
                number.is_active=False
                if number.connection_status=='connected':
                    number.connection_status='disconnected'
                number.save(update_fields=['is_active','connection_status','updated_at'])
                messages.success(
                    request,
                    f'«{label}» آرشیو شد؛ سابقه پیام‌ها و آمار آن حفظ شد.',
                )
            else:
                number.delete()
                messages.success(request,f'«{label}» حذف شد.')
            return redirect('whatsapp_hub')

        if action=='toggle_active':
            number=get_object_or_404(WhatsAppNumber,pk=request.POST.get('number_id'))
            number.is_active=not number.is_active
            number.save(update_fields=['is_active','updated_at'])
            messages.success(request,'وضعیت شماره به‌روزرسانی شد.')
            return redirect('whatsapp_hub')

    today=timezone.localdate()
    numbers=list(
        WhatsAppNumber.objects
        .select_related('branch','responsible__user')
        .annotate(
            today_messages=Count(
                'messages',
                filter=Q(messages__created_at__date=today),
            ),
            today_inbound=Count(
                'messages',
                filter=Q(messages__created_at__date=today,messages__direction='inbound'),
            ),
            today_outbound=Count(
                'messages',
                filter=Q(messages__created_at__date=today,messages__direction='outbound'),
            ),
            today_manual=Count(
                'messages',
                filter=Q(
                    messages__created_at__date=today,
                    messages__direction='outbound',
                    messages__outbound_mode='manual',
                ),
            ),
            today_automation=Count(
                'messages',
                filter=Q(
                    messages__created_at__date=today,
                    messages__direction='outbound',
                    messages__outbound_mode='automation',
                ),
            ),
            today_ai=Count(
                'messages',
                filter=Q(messages__created_at__date=today,messages__direction='outbound')
                & (Q(messages__outbound_mode='ai') | Q(messages__is_ai=True)),
            ),
            unread_messages=Count(
                'messages',
                filter=Q(
                    messages__direction='inbound',
                    messages__is_read_by_staff=False,
                ),
            ),
            latest_message_at=Max('messages__created_at'),
        )
    )

    for item in numbers:
        activity=item.today_messages
        if activity >= 80:
            item.activity_label='خیلی فعال'
            item.activity_class='hot'
        elif activity >= 30:
            item.activity_label='فعال'
            item.activity_class='good'
        elif activity >= 10:
            item.activity_label='متوسط'
            item.activity_class='mid'
        elif activity > 0:
            item.activity_label='کم‌فعال'
            item.activity_class='low'
        else:
            item.activity_label='بدون فعالیت'
            item.activity_class='idle'
        item.last_activity_at=item.latest_message_at or item.last_webhook_at
        if item.responsible:
            item.owner_name=item.responsible.user.get_full_name() or item.responsible.user.username
        else:
            item.owner_name=item.display_name or '—'

    recent_messages=list(
        WhatsAppMessage.objects
        .select_related('whatsapp_number','sent_by')
        .order_by('-created_at')[:30]
    )

    # 30-day activity chart. Total activity includes every inbound/outbound
    # message regardless of whether the reply was manual, automation, or AI.
    chart_days=30
    chart_start=today-timedelta(days=chart_days-1)
    chart_dates=[chart_start+timedelta(days=offset) for offset in range(chart_days)]
    chart_palette=[
        '#36e6a5','#aa78ff','#2aa8ff','#ffc43d','#ff5eb7',
        '#35d4f4','#ff8a34','#ff5d68','#8f9dff','#67e3d4',
    ]

    period_counts={
        row['whatsapp_number_id']:row['total']
        for row in (
            WhatsAppMessage.objects
            .filter(created_at__date__gte=chart_start,created_at__date__lte=today)
            .values('whatsapp_number_id')
            .annotate(total=Count('id'))
        )
    }
    chart_numbers=sorted(
        numbers,
        key=lambda item:(period_counts.get(item.id,0),item.today_messages,item.id),
        reverse=True,
    )[:10]
    chart_number_ids=[item.id for item in chart_numbers]

    by_number_day={}
    if chart_number_ids:
        grouped=(
            WhatsAppMessage.objects
            .filter(
                whatsapp_number_id__in=chart_number_ids,
                created_at__date__gte=chart_start,
                created_at__date__lte=today,
            )
            .annotate(day=TruncDate('created_at',tzinfo=timezone.get_current_timezone()))
            .values('whatsapp_number_id','day')
            .annotate(total=Count('id'))
        )
        for row in grouped:
            by_number_day[(row['whatsapp_number_id'],row['day'])]=row['total']

    chart_series=[]
    for index,item in enumerate(chart_numbers):
        chart_series.append({
            'id':item.id,
            'label':item.label,
            'phone':item.phone_number,
            'color':chart_palette[index % len(chart_palette)],
            'values':[by_number_day.get((item.id,day),0) for day in chart_dates],
            'total':period_counts.get(item.id,0),
        })

    persian_months=[
        'ژانویه','فوریه','مارس','آوریل','مه','ژوئن',
        'ژوئیه','اوت','سپتامبر','اکتبر','نوامبر','دسامبر',
    ]
    chart_labels=[
        f'{day.day} {persian_months[day.month-1]}'
        for day in chart_dates
    ]
    chart_data={
        'labels':chart_labels,
        'series':chart_series,
        'days':chart_days,
    }

    most_active=max(numbers,key=lambda item:item.today_messages,default=None)
    stats={
        'total_numbers':len(numbers),
        'connected_numbers':sum(1 for item in numbers if item.connection_status=='connected' and item.is_active),
        'today_messages':sum(item.today_messages for item in numbers),
        'unread_messages':sum(item.unread_messages for item in numbers),
        'today_inbound':sum(item.today_inbound for item in numbers),
        'today_outbound':sum(item.today_outbound for item in numbers),
        'today_manual':sum(item.today_manual for item in numbers),
        'today_automation':sum(item.today_automation for item in numbers),
        'today_ai':sum(item.today_ai for item in numbers),
        'today_delivered':WhatsAppMessage.objects.filter(
            created_at__date=today,status__in=['delivered','read'],
        ).count(),
        'most_active_label':most_active.label if most_active and most_active.today_messages else '—',
        'most_active_count':most_active.today_messages if most_active else 0,
    }

    response=render(request,'core/whatsapp_hub.html',{
        'numbers':numbers,
        'recent_messages':recent_messages,
        'branches':Branch.objects.filter(is_active=True).order_by('name'),
        'responsibles':EmployeeProfile.objects.filter(
            is_active=True,user__is_active=True,
            role__in=['call_center','manager','internal_manager','admin','consultant','receptionist'],
        ).select_related('user','branch').order_by('user__first_name','user__last_name','user__username'),
        'number_types':WhatsAppNumber.TYPE_CHOICES,
        'stats':stats,
        'chart_data':chart_data,
    })
    response['Cache-Control']='no-store, private'
    return response
