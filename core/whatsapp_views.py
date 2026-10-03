from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Max, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Branch, EmployeeProfile, WhatsAppMessage, WhatsAppNumber
from .views import _is_executive_user


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
    })
    response['Cache-Control']='no-store, private'
    return response
