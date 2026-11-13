"""Operational LIGHT workspace. Uses existing request/booking authorization."""
from datetime import datetime
from urllib.parse import urlencode
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Prefetch
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST
from .models import CustomerRequestEvent, CustomerIntakePhoto, VisitAppointment
from .customer_portal_views import _staff_gate, _role, _visible_staff_requests

def rows(request):
    _staff_gate(request)
    if _role(request) not in ('call_center','admin','internal_manager','manager'): raise PermissionDenied()
    return _visible_staff_requests(request).filter(kind='visit')

def private_render(request,template,ctx):
    response=render(request,template,ctx);response['Cache-Control']='private, no-store';return response

@require_GET
def workspace(request):
    base=rows(request);now=timezone.now();profile=getattr(request.user,'profile',None)
    active=base.filter(status__in=('pending','contacted'))
    stats={'new':base.filter(status='pending').count(),'mine':active.filter(assigned_to=profile).count() if profile else 0,'overdue':active.filter(next_followup_at__lte=now).count(),'booked':base.filter(status='booked').count()}
    selected=request.GET.get('view','active');q=request.GET.get('q','').strip()[:100]
    filters={'active':Q(status__in=('pending','contacted')),'new':Q(status='pending'),'mine':Q(status__in=('pending','contacted'),assigned_to=profile) if profile else Q(pk__in=[]),'overdue':Q(status__in=('pending','contacted'),next_followup_at__lte=now),'booked':Q(status='booked'),'closed':Q(status='declined'),'all':Q()}
    if selected not in filters:selected='active'
    qs=base.filter(filters[selected])
    if q: qs=qs.filter(Q(member__full_name__icontains=q)|Q(member__phone__icontains=q))
    page=Paginator(qs.select_related('intake').order_by('next_followup_at','created_at','pk'),25).get_page(request.GET.get('page'))
    return private_render(request,'core/me_desk_list.html',{'page':page,'stats':stats,'selected':selected,'q':q,'query':urlencode({'view':selected,'q':q}),'now':now})

@require_GET
def detail(request,pk):
    row=get_object_or_404(rows(request).select_related('intake'),pk=pk)
    intake=getattr(row,'intake',None)
    photos=list(intake.photos.defer('content')) if intake else []
    editable=row.status in ('pending','contacted') and (not row.assigned_to_id or row.assigned_to_id==getattr(getattr(request.user,'profile',None),'pk',None) or _role(request) in ('admin','internal_manager'))
    phone=row.member.phone;variants=[phone,'+98'+phone[1:],'98'+phone[1:]]
    bookings=VisitAppointment.objects.filter(branch_id=row.branch_id,phone__in=variants,status__in=('booked','arrived','completed')).order_by('-appointment_date','-pk')[:15]
    history=rows(request).filter(member_id=row.member_id).exclude(pk=row.pk).order_by('-created_at')[:10]
    return private_render(request,'core/me_desk_detail.html',{'row':row,'intake':intake,'photos':photos,'events':row.followup_events.select_related('actor')[:100],'editable':editable,'bookings':bookings,'history':history,'now':timezone.now()})

@require_POST
def followup(request,pk):
    with transaction.atomic():
        row=get_object_or_404(rows(request).select_for_update(of=('self',)),pk=pk)
        profile=getattr(request.user,'profile',None)
        if row.status not in ('pending','contacted'): raise PermissionDenied('این درخواست بسته یا نوبت‌دهی شده است.')
        if row.assigned_to_id and row.assigned_to_id!=getattr(profile,'pk',None) and _role(request) not in ('admin','internal_manager'): raise PermissionDenied('پیگیری این پرونده با کارشناس دیگری است.')
        action=request.POST.get('outcome');note=request.POST.get('note','').strip();raw=request.POST.get('next_contact','').strip()
        labels={'no_answer':'پاسخ نداد','contacted':'گفت‌وگو انجام شد','callback':'تماس مجدد','note':'یادداشت داخلی'}
        due=None
        try:
            if action not in labels or not note or len(note)>1000: raise ValueError()
            if raw:
                due=datetime.fromisoformat(raw)
                if timezone.is_naive(due): due=timezone.make_aware(due)
                if due<=timezone.now(): raise ValueError()
            if action in ('callback','no_answer') and not due: raise ValueError()
        except (ValueError,TypeError):
            messages.error(request,'نتیجه و توضیح پیگیری را کامل کنید؛ برای تماس مجدد یا پاسخ‌ندادن، زمان آینده لازم است.')
            return redirect('me_desk_detail',pk=pk)
        row.status='contacted'
        if not row.assigned_to_id: row.assigned_to=profile
        if action!='note' or due:row.next_followup_at=due
        row.save(update_fields=['status','assigned_to','next_followup_at','updated_at'])
        CustomerRequestEvent.objects.create(request=row,actor=request.user,action=labels[action],note=note,status=row.status,next_followup_at=row.next_followup_at)
    messages.success(request,'پیگیری و زمان تماس در پرونده ذخیره شد.')
    return redirect('me_desk_detail',pk=pk)
