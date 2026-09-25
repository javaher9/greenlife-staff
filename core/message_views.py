"""Internal staff messaging views. Also marks this release as an application rebuild after safe backup cleanup."""

from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.http import JsonResponse
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

    recent_direct=list(
        InternalMessage.objects.filter(
            Q(sender=request.user,recipient__isnull=False) |
            Q(recipient=request.user)
        ).select_related('sender','recipient').order_by('-created_at')[:500]
    )
    last_by_contact={}
    for item in recent_direct:
        other_id=item.recipient_id if item.sender_id==request.user.pk else item.sender_id
        if other_id and other_id not in last_by_contact:
            last_by_contact[other_id]=item

    contact_rows=[
        {
            'user':u,
            'unread':unread_by_sender.get(u.pk,0),
            'last_message':last_by_contact.get(u.pk),
        }
        for u in contacts
    ]
    contact_rows.sort(
        key=lambda row:(
            1 if row['unread'] else 0,
            row['last_message'].created_at.timestamp() if row['last_message'] else 0,
        ),
        reverse=True,
    )
    unread_total=sum(unread_by_sender.values())

    response=render(request,'core/internal_messages.html',{
        'contact_rows':contact_rows,
        'selected_contact':selected,
        'thread':thread,
        'room_title':room_title,
        'room_subtitle':room_subtitle,
        'unread_total':unread_total,
        'staff_count':len(contacts)+1,
        'room_kind':'خصوصی' if selected else 'عمومی',
    })
    response['Cache-Control']='no-store, private'
    return response


@_staff_messaging_required
def internal_message_updates(request):
    contacts=list(_staff_users().exclude(pk=request.user.pk))
    contact_ids={u.pk for u in contacts}
    selected_id=(request.GET.get('with') or '').strip()
    selected=None
    if selected_id:
        if not selected_id.isdigit() or int(selected_id) not in contact_ids:
            return JsonResponse({'ok':False,'error':'invalid contact'},status=400)
        selected=next((u for u in contacts if u.pk==int(selected_id)),None)

    try:
        after=max(0,int(request.GET.get('after') or 0))
    except (TypeError,ValueError):
        after=0

    if selected:
        qs=InternalMessage.objects.filter(
            Q(sender=request.user,recipient=selected) |
            Q(sender=selected,recipient=request.user),
            pk__gt=after,
        ).select_related('sender','recipient').order_by('pk')[:100]
        InternalMessage.objects.filter(
            sender=selected,recipient=request.user,read_at__isnull=True
        ).update(read_at=timezone.now())
    else:
        qs=InternalMessage.objects.filter(
            recipient__isnull=True,pk__gt=after
        ).select_related('sender').order_by('pk')[:100]

    data=[]
    for item in qs:
        data.append({
            'id':item.pk,
            'sender':item.sender.get_full_name() or item.sender.username,
            'body':item.body,
            'mine':item.sender_id==request.user.pk,
            'time':timezone.localtime(item.created_at).strftime('%H:%M'),
        })
    response=JsonResponse({'ok':True,'messages':data})
    response['Cache-Control']='no-store, private'
    return response



@_staff_messaging_required
def internal_message_live_widget(request):
    """Compact live-chat API used on every staff page.

    GET returns contacts, unread counts and an optional direct thread.
    POST sends a direct message without leaving the current page.
    """
    contacts=list(_staff_users().exclude(pk=request.user.pk))
    contact_map={u.pk:u for u in contacts}

    if request.method=='POST':
        target=(request.POST.get('recipient') or '').strip()
        body=(request.POST.get('body') or '').strip()
        if not target.isdigit() or int(target) not in contact_map:
            return JsonResponse({'ok':False,'error':'گیرنده معتبر نیست.'},status=400)
        if not body:
            return JsonResponse({'ok':False,'error':'متن پیام خالی است.'},status=400)
        if len(body)>2000:
            return JsonResponse({'ok':False,'error':'پیام حداکثر ۲۰۰۰ کاراکتر می‌تواند باشد.'},status=400)

        recipient=contact_map[int(target)]
        item=InternalMessage.objects.create(
            sender=request.user,
            recipient=recipient,
            body=body,
        )
        StaffNotification.objects.create(
            user=recipient,
            title='پیام داخلی جدید',
            message=f'{request.user.get_full_name() or request.user.username}: {body[:140]}',
            notification_type='internal_message',
        )
        return JsonResponse({
            'ok':True,
            'message':{
                'id':item.pk,
                'sender_id':request.user.pk,
                'sender':request.user.get_full_name() or request.user.username,
                'body':item.body,
                'mine':True,
                'time':timezone.localtime(item.created_at).strftime('%H:%M'),
            },
        })

    selected_id=(request.GET.get('with') or '').strip()
    selected=contact_map.get(int(selected_id)) if selected_id.isdigit() else None

    unread_by_sender={}
    for sender_id in InternalMessage.objects.filter(
        recipient=request.user,
        read_at__isnull=True,
    ).values_list('sender_id',flat=True):
        unread_by_sender[sender_id]=unread_by_sender.get(sender_id,0)+1

    recent_direct=list(
        InternalMessage.objects.filter(
            Q(sender=request.user,recipient__isnull=False) |
            Q(recipient=request.user)
        )
        .select_related('sender','recipient','sender__profile','recipient__profile')
        .order_by('-created_at')[:500]
    )
    last_by_contact={}
    for item in recent_direct:
        other_id=item.recipient_id if item.sender_id==request.user.pk else item.sender_id
        if other_id and other_id not in last_by_contact:
            last_by_contact[other_id]=item

    rows=[]
    for user in contacts:
        last=last_by_contact.get(user.pk)
        rows.append({
            'id':user.pk,
            'name':user.get_full_name() or user.username,
            'role':getattr(user.profile,'job_title','') or user.profile.get_role_display(),
            'branch':str(user.profile.branch or ''),
            'unread':unread_by_sender.get(user.pk,0),
            'last_body':(last.body[:90] if last else ''),
            'last_time':(timezone.localtime(last.created_at).strftime('%H:%M') if last else ''),
            'last_ts':(last.created_at.timestamp() if last else 0),
            'avatar':(user.profile.avatar.url if getattr(user.profile,'avatar',None) else ''),
        })
    rows.sort(key=lambda row:(1 if row['unread'] else 0,row['last_ts']),reverse=True)

    thread=[]
    if selected:
        qs=(
            InternalMessage.objects
            .filter(
                Q(sender=request.user,recipient=selected) |
                Q(sender=selected,recipient=request.user)
            )
            .select_related('sender','recipient','sender__profile','recipient__profile')
            .order_by('-created_at')[:60]
        )
        thread=list(reversed(list(qs)))
        InternalMessage.objects.filter(
            sender=selected,
            recipient=request.user,
            read_at__isnull=True,
        ).update(read_at=timezone.now())
        unread_by_sender[selected.pk]=0
        for row in rows:
            if row['id']==selected.pk:
                row['unread']=0
                break

    payload=[]
    for item in thread:
        payload.append({
            'id':item.pk,
            'sender_id':item.sender_id,
            'sender':item.sender.get_full_name() or item.sender.username,
            'body':item.body,
            'mine':item.sender_id==request.user.pk,
            'time':timezone.localtime(item.created_at).strftime('%H:%M'),
            'avatar':(
                item.sender.profile.avatar.url
                if getattr(getattr(item.sender,'profile',None),'avatar',None)
                else ''
            ),
        })

    latest_incoming_item=(
        InternalMessage.objects
        .filter(recipient=request.user)
        .select_related('sender','sender__profile')
        .order_by('-pk')
        .first()
    )
    latest_incoming=latest_incoming_item.pk if latest_incoming_item else 0
    incoming_preview=None
    if latest_incoming_item:
        incoming_preview={
            'id':latest_incoming_item.pk,
            'sender_id':latest_incoming_item.sender_id,
            'sender':latest_incoming_item.sender.get_full_name() or latest_incoming_item.sender.username,
            'body':latest_incoming_item.body[:180],
            'time':timezone.localtime(latest_incoming_item.created_at).strftime('%H:%M'),
            'avatar':(
                latest_incoming_item.sender.profile.avatar.url
                if getattr(getattr(latest_incoming_item.sender,'profile',None),'avatar',None)
                else ''
            ),
        }

    response=JsonResponse({
        'ok':True,
        'contacts':rows[:40],
        'thread':payload,
        'selected':selected.pk if selected else None,
        'unread_total':sum(unread_by_sender.values()),
        'latest_incoming_id':latest_incoming,
        'incoming_preview':incoming_preview,
    })
    response['Cache-Control']='no-store, private'
    return response
