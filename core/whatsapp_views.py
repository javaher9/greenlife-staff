from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import Branch, WhatsAppMessage, WhatsAppNumber
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

            if not label or not phone:
                messages.error(request,'نام شماره و خود شماره واتساپ الزامی است.')
                return redirect('whatsapp_hub')

            if phone_number_id and WhatsAppNumber.objects.filter(phone_number_id=phone_number_id).exists():
                messages.error(request,'این Phone Number ID قبلاً ثبت شده است.')
                return redirect('whatsapp_hub')

            branch=None
            if branch_id:
                branch=Branch.objects.filter(pk=branch_id,is_active=True).first()

            WhatsAppNumber.objects.create(
                label=label[:100],
                phone_number=phone[:32],
                phone_number_id=phone_number_id,
                business_account_id=business_account_id[:120],
                branch=branch,
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
        .select_related('branch')
        .annotate(
            today_messages=Count(
                'messages',
                filter=Q(messages__created_at__date=today),
            ),
            unread_messages=Count(
                'messages',
                filter=Q(
                    messages__direction='inbound',
                    messages__is_read_by_staff=False,
                ),
            ),
        )
    )

    recent_messages=list(
        WhatsAppMessage.objects
        .select_related('whatsapp_number','sent_by')
        .order_by('-created_at')[:30]
    )

    stats={
        'total_numbers':len(numbers),
        'connected_numbers':sum(1 for item in numbers if item.connection_status=='connected' and item.is_active),
        'today_messages':sum(item.today_messages for item in numbers),
        'unread_messages':sum(item.unread_messages for item in numbers),
        'today_inbound':WhatsAppMessage.objects.filter(
            created_at__date=today,direction='inbound',
        ).count(),
        'today_outbound':WhatsAppMessage.objects.filter(
            created_at__date=today,direction='outbound',
        ).count(),
        'today_ai':WhatsAppMessage.objects.filter(
            created_at__date=today,direction='outbound',is_ai=True,
        ).count(),
        'today_delivered':WhatsAppMessage.objects.filter(
            created_at__date=today,status__in=['delivered','read'],
        ).count(),
    }

    response=render(request,'core/whatsapp_hub.html',{
        'numbers':numbers,
        'recent_messages':recent_messages,
        'branches':Branch.objects.filter(is_active=True).order_by('name'),
        'stats':stats,
    })
    response['Cache-Control']='no-store, private'
    return response
