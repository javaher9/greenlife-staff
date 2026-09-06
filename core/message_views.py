"""Internal staff messaging; redeploy marker for disk-safe production rollout."""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import InternalMessage, StaffNotification


def _staff_users():
    return (
        User.objects.filter(
            is_active=True,
            profile__is_active=True,
        )
        .exclude(profile__role='referrer')
        .select_related('profile','profile__branch')
        .order_by('profile__branch__name','first_name','last_name','username')
    )


def _staff_messaging_required(view):
    @wraps(view)
    @login_required
    def wrapper(request,*args,**kwargs):
        role=getattr(getattr(request.user,'profile',None),'role','employee')
        if role=='referrer':
            raise PermissionDenied('پیام داخلی فقط برای پرسنل است.')
        return view(request,*args,**kwargs)
    return wrapper


@_staff_messaging_required
def internal_messages(request):
    contacts=list(_staff_users().exclude(pk=request.user.pk))
    contact_ids={u.pk for u in contacts}
    selected_id=(request.GET.get('with') or '').strip()
    selected=None
    if selected_id.isdigit() and int(selected_id) in contact_ids:
        selected=next((u for u in contacts if u.pk==int(selected_id)),None)

    if request.method=='POST':
        body=(request.POST.get('body') or '').strip()
        target=(request.POST.get('recipient') or 'all').strip()
        recipient=None
        if target!='all':
            if not target.isdigit() or int(target) not in contact_ids:
                messages.error(request,'گیرنده معتبر نیست.')
                return redirect('internal_messages')
            recipient=next((u for u in contacts if u.pk==int(target)),None)

        if not body:
            messages.error(request,'متن پیام خالی است.')
        elif len(body)>2000:
            messages.error(request,'پیام حداکثر ۲۰۰۰ کاراکتر می‌تواند باشد.')
        else:
            InternalMessage.objects.create(
                sender=request.user,
                recipient=recipient,
                body=body,
            )
            if recipient:
                StaffNotification.objects.create(
                    user=recipient,
                    title='پیام داخلی جدید',
                    message=f'{request.user.get_full_name() or request.user.username}: {body[:140]}',
                    notification_type='internal_message',
                )
                messages.success(request,'پیام ارسال شد.')
                return redirect(f"{reverse('internal_messages')}?with={recipient.pk}")
            messages.success(request,'پیام در گفتگوی عمومی ارسال شد.')
            return redirect('internal_messages')

    if selected:
        thread_qs=InternalMessage.objects.filter(
            Q(sender=request.user,recipient=selected) |
            Q(sender=selected,recipient=request.user)
        ).select_related('sender','recipient').order_by('-created_at')[:200]
        InternalMessage.objects.filter(
            sender=selected,recipient=request.user,read_at__isnull=True
        ).update(read_at=timezone.now())
        room_title=selected.get_full_name() or selected.username
        room_subtitle=f"{getattr(selected.profile,'job_title','') or selected.profile.get_role_display()} · {selected.profile.branch or 'بدون شعبه'}"
    else:
        thread_qs=InternalMessage.objects.filter(
            recipient__isnull=True
        ).select_related('sender').order_by('-created_at')[:200]
        room_title='گفتگوی عمومی پرسنل'
        room_subtitle='همه پرسنل فعال می‌توانند این گفتگو را ببینند و پاسخ دهند.'

    thread=list(reversed(list(thread_qs)))
    unread_by_sender={}
    for sender_id in InternalMessage.objects.filter(
        recipient=request.user,read_at__isnull=True
    ).values_list('sender_id',flat=True):
        unread_by_sender[sender_id]=unread_by_sender.get(sender_id,0)+1

    contact_rows=[
        {
            'user':u,
            'unread':unread_by_sender.get(u.pk,0),
        }
        for u in contacts
    ]
    unread_total=sum(unread_by_sender.values())

    response=render(request,'core/internal_messages.html',{
        'contact_rows':contact_rows,
        'selected_contact':selected,
        'thread':thread,
        'room_title':room_title,
        'room_subtitle':room_subtitle,
        'unread_total':unread_total,
    })
    response['Cache-Control']='no-store, private'
    return response
