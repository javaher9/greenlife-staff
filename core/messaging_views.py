from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from .forms import InternalConversationCreateForm
from .models import InternalConversation, InternalMessage, StaffNotification


def _staff_role(user):
    return getattr(getattr(user,'profile',None),'role','employee')


def staff_messaging_required(view):
    @wraps(view)
    @login_required
    def wrapper(request,*args,**kwargs):
        if _staff_role(request.user)=='referrer':
            raise PermissionDenied('کارتابل داخلی فقط برای پرسنل است.')
        return view(request,*args,**kwargs)
    return wrapper


def _conversation_for(user,pk):
    return get_object_or_404(
        InternalConversation.objects.prefetch_related('participants__profile','participants__profile__branch'),
        pk=pk,participants=user,
    )


def _display_title(conversation,user):
    if conversation.title:
        return conversation.title
    others=[u.get_full_name() or u.username for u in conversation.participants.all() if u.pk!=user.pk]
    return '، '.join(others[:4]) or 'گفتگوی داخلی'


def _notify_message(message):
    sender_name=(message.sender.get_full_name() or message.sender.username) if message.sender else 'سیستم'
    body=' '.join((message.body or '').split())
    for user in message.conversation.participants.exclude(pk=message.sender_id):
        StaffNotification.objects.create(
            user=user,
            title='پیام داخلی جدید',
            message=f'{sender_name}: {body[:140]}',
            notification_type='internal_message',
        )


@staff_messaging_required
def internal_message_inbox(request):
    conversations=(
        InternalConversation.objects.filter(participants=request.user)
        .annotate(last_message_at=Max('messages__created_at'))
        .prefetch_related('participants__profile','participants__profile__branch')
        .order_by('-last_message_at','-updated_at','-id')
    )
    rows=[]
    for conversation in conversations:
        last=conversation.messages.select_related('sender').order_by('-created_at','-id').first()
        unread=conversation.messages.exclude(sender=request.user).exclude(read_by=request.user).count()
        rows.append({
            'conversation':conversation,
            'title':_display_title(conversation,request.user),
            'last':last,
            'unread':unread,
            'participant_count':conversation.participants.count(),
        })
    return render(request,'core/internal_messages/inbox.html',{'conversation_rows':rows})


@staff_messaging_required
def internal_message_new(request):
    form=InternalConversationCreateForm(request.POST or None,user=request.user)
    if request.method=='POST' and form.is_valid():
        participants=list(form.cleaned_data['participants'])
        with transaction.atomic():
            conversation=InternalConversation.objects.create(
                title=(form.cleaned_data.get('title') or '').strip(),
                created_by=request.user,
            )
            conversation.participants.add(request.user,*participants)
            message=InternalMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                body=form.cleaned_data['first_message'],
            )
            message.read_by.add(request.user)
            InternalConversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
            _notify_message(message)
        return redirect('internal_message_thread',pk=conversation.pk)
    return render(request,'core/internal_messages/new.html',{'form':form})


@staff_messaging_required
def internal_message_thread(request,pk):
    conversation=_conversation_for(request.user,pk)
    if request.method=='POST':
        body=(request.POST.get('body') or '').strip()
        if not body:
            messages.error(request,'پیام نمی‌تواند خالی باشد.')
        elif len(body)>5000:
            messages.error(request,'پیام بیش از حد طولانی است.')
        else:
            with transaction.atomic():
                item=InternalMessage.objects.create(
                    conversation=conversation,sender=request.user,body=body,
                )
                item.read_by.add(request.user)
                InternalConversation.objects.filter(pk=conversation.pk).update(updated_at=timezone.now())
                _notify_message(item)
            return redirect('internal_message_thread',pk=conversation.pk)

    messages_qs=list(conversation.messages.select_related('sender','sender__profile').order_by('created_at','id')[:500])
    unread_ids=[m.pk for m in messages_qs if m.sender_id!=request.user.pk and not m.read_by.filter(pk=request.user.pk).exists()]
    if unread_ids:
        through=InternalMessage.read_by.through
        through.objects.bulk_create([
            through(internalmessage_id=message_id,user_id=request.user.pk) for message_id in unread_ids
        ],ignore_conflicts=True)
    participants=[u for u in conversation.participants.all()]
    return render(request,'core/internal_messages/thread.html',{
        'conversation':conversation,
        'conversation_title':_display_title(conversation,request.user),
        'thread_messages':messages_qs,
        'conversation_participants':participants,
    })


@staff_messaging_required
def internal_message_updates(request,pk):
    conversation=_conversation_for(request.user,pk)
    try:
        after=max(0,int(request.GET.get('after') or 0))
    except (TypeError,ValueError):
        after=0
    qs=list(conversation.messages.filter(pk__gt=after).select_related('sender').order_by('pk')[:100])
    other_ids=[m.pk for m in qs if m.sender_id!=request.user.pk]
    if other_ids:
        through=InternalMessage.read_by.through
        through.objects.bulk_create([
            through(internalmessage_id=message_id,user_id=request.user.pk) for message_id in other_ids
        ],ignore_conflicts=True)
    data=[]
    for item in qs:
        sender_name=(item.sender.get_full_name() or item.sender.username) if item.sender else 'سیستم'
        data.append({
            'id':item.pk,
            'sender':sender_name,
            'body':item.body,
            'time':timezone.localtime(item.created_at).strftime('%H:%M'),
            'own':item.sender_id==request.user.pk,
        })
    return JsonResponse({'ok':True,'messages':data})
