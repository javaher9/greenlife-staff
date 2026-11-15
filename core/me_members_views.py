"""Executive member overview. Registration, attendance and usage remain distinct."""
import uuid
from decimal import Decimal
from collections import defaultdict
from datetime import timedelta, datetime
from functools import wraps
from urllib.parse import urlencode
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Count, Sum, Exists, OuterRef, Subquery, Value, DateTimeField
from django.db.models.functions import Coalesce, Greatest, Concat, Substr, TruncDate
from django.http import HttpResponseBadRequest
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_GET, require_http_methods
from .models import FinancialTransaction, lead_phone_variants, CustomerPortalMember, PatientProfile, PatientDietProgram, VisitAppointment, CustomerServiceRequest
from .jalali import parse_jalali, format_jalali, LATIN_DIGITS
from .me_diet_models import MeMealReport
from .me_members_models import MeMemberCare, MeMemberAction
from .customer_portal_views import _member


def may_manage(user):
    p=getattr(user,'profile',None)
    return bool(user.is_authenticated and user.is_active and (not p or p.is_active) and (user.is_superuser or user.username.lower() in settings.EXECUTIVE_USERNAMES or getattr(p,'role',None) in ('admin','internal_manager')))

def gate(view):
    @wraps(view)
    @login_required
    def wrapped(request,*args,**kwargs):
        if not may_manage(request.user):raise PermissionDenied()
        return view(request,*args,**kwargs)
    return wrapped

def private(request,template,ctx,status=200):
    r=render(request,template,ctx,status=status);r['Cache-Control']='private, no-store';return r

def phone_q(field):
    return Q(**{field:OuterRef('phone')})|Q(**{field:Concat(Value('+98'),Substr(OuterRef('phone'),2))})|Q(**{field:Concat(Value('98'),Substr(OuterRef('phone'),2))})

def members():
    patient=PatientProfile.objects.filter(phone_q('phone')).order_by('pk')
    visits=VisitAppointment.objects.filter(phone_q('phone'),status__in=('arrived','completed'))
    unread=MeMealReport.objects.filter(member_id=OuterRef('pk')).exclude(note='').filter(Q(updated_at__gt=OuterRef('me_care__reviewed_at'))|Q(member__me_care__reviewed_at__isnull=True))
    return CustomerPortalMember.objects.select_related('me_care__assigned_to','me_state').annotate(
        patient_id=Subquery(patient.values('pk')[:1]),patient_name=Subquery(patient.values('full_name')[:1]),
        last_mode=Subquery(visits.order_by('-appointment_date','-appointment_time','-pk').values('visit_mode')[:1]),
        has_online=Exists(visits.filter(visit_mode='online')),has_in_person=Exists(visits.filter(visit_mode='in_person')),
        past_program=Exists(PatientDietProgram.objects.filter(phone_q('patient__phone'),status='completed')),
        paused_program=Exists(PatientDietProgram.objects.filter(phone_q('patient__phone'),status='paused')),branch_name=Subquery(patient.values('home_branch__name')[:1]),
        visited=Exists(visits),has_program=Exists(PatientDietProgram.objects.filter(phone_q('patient__phone'),status='active')),
        has_note=Exists(unread),has_request=Exists(CustomerServiceRequest.objects.filter(member_id=OuterRef('pk'),status__in=('pending','contacted'))),
        last_seen=Greatest(Coalesce('last_login_at','created_at'),Coalesce('me_state__updated_at','created_at')),
        heart_count=Count('me_awards',distinct=True),meal_count=Count('me_meals',distinct=True),
    )

def attention_q(now):
    return Q(has_note=True)|Q(has_request=True)|Q(me_care__followup_at__lte=now)

def masked_phone(user,phone):
    if user.is_superuser or user.username.lower() in settings.EXECUTIVE_USERNAMES or getattr(getattr(user,'profile',None),'role',None)=='admin':return phone
    return phone[:4]+'***'+phone[-4:]

def may_view_payments(user):
    return bool(user.is_superuser or user.username.lower() in settings.EXECUTIVE_USERNAMES or getattr(getattr(user,'profile',None),'role',None)=='admin')

def attach_payments(user, rows):
    """Batch approved receipts, once per transaction; amounts are stored in rials.

    An explicit appointment is authoritative over a conflicting free-text reference.
    Ambiguous CRM references are never attributed to multiple members.
    """
    for m in rows:
        m.show_payments=may_view_payments(user)
    if not rows or not may_view_payments(user):return
    by_phone=defaultdict(set)
    by_ref=defaultdict(set)
    totals={m.pk:Decimal('0') for m in rows}
    for m in rows:
        for phone in lead_phone_variants(m.phone):
            by_phone[phone].add(m.pk)
            by_ref[phone].add(m.pk)
    for patient in PatientProfile.objects.filter(phone__in=by_phone).exclude(crm_id='').values('phone','crm_id'):
        if patient['crm_id']:by_ref[patient['crm_id']].update(by_phone[patient['phone']])
    entries=FinancialTransaction.objects.filter(entry_type='inc',review_status='approved').filter(Q(appointment__phone__in=by_phone)|Q(patient_ref__in=by_ref)).values('amount','appointment_id','appointment__phone','patient_ref')
    for entry in entries:
        targets=by_phone.get(entry['appointment__phone'],set()) if entry['appointment_id'] else by_ref.get(entry['patient_ref'],set())
        if len(targets)==1:totals[next(iter(targets))]+=entry['amount']
    for m in rows:m.paid_total=totals[m.pk]

def decorate(request,rows,now):
    for m in rows:
        c=getattr(m,'me_care',None)
        m.phone_display=masked_phone(request.user,m.phone)
        m.display_name=m.full_name.strip() or m.patient_name or 'عضو بدون نام'
        m.overdue=bool(c and c.followup_at and c.followup_at<=now)
        m.needs_attention=m.has_note or m.has_request or m.overdue
    attach_payments(request.user,rows)
    return rows

@gate
@require_GET
def dashboard(request):
    now=timezone.now();base=members();week=now-timedelta(days=7)
    counts=base.aggregate(c_total=Count('pk',distinct=True),c_new=Count('pk',filter=Q(created_at__gte=week),distinct=True),c_active=Count('pk',filter=Q(last_seen__gte=week),distinct=True),c_program=Count('pk',filter=Q(has_program=True),distinct=True),c_visited=Count('pk',filter=Q(visited=True),distinct=True),c_unvisited=Count('pk',filter=Q(visited=False),distinct=True),c_attention=Count('pk',filter=attention_q(now),distinct=True),c_sync=Count('pk',filter=Q(me_state__isnull=False),distinct=True),c_notes=Count('pk',filter=Q(has_note=True),distinct=True),c_requests=Count('pk',filter=Q(has_request=True),distinct=True),c_overdue=Count('pk',filter=Q(me_care__followup_at__lte=now),distinct=True),c_quiet=Count('pk',filter=Q(last_seen__lt=week),distinct=True))
    counts={k[2:]:v for k,v in counts.items()}
    groups={'all':Q(),'new':Q(created_at__gte=week),'active':Q(last_seen__gte=week),'program':Q(has_program=True),'visited':Q(visited=True),'unvisited':Q(visited=False),'attention':attention_q(now),'notes':Q(has_note=True),'requests':Q(has_request=True),'overdue':Q(me_care__followup_at__lte=now),'quiet':Q(last_seen__lt=week),'sync':Q(me_state__isnull=False)}
    selected=request.GET.get('group','all');selected=selected if selected in groups else 'all'
    q=request.GET.get('q','').strip()[:100];qs=base.filter(groups[selected])
    # Restricted managers cannot use phone search as an existence oracle.
    if q:qs=qs.filter(Q(full_name__icontains=q)|(Q(phone__icontains=q) if masked_phone(request.user,'09123456789')=='09123456789' else Q(pk__in=[])))
    sort=request.GET.get('sort','attention');sort=sort if sort in ('attention','recent','new') else 'attention'
    qs=qs.annotate(attention=Exists(base.filter(pk=OuterRef('pk')).filter(attention_q(now)))) if sort=='attention' else qs
    order={'attention':('-attention','-last_seen','-pk'),'recent':('-last_seen','-pk'),'new':('-created_at','-pk')}[sort]
    page=Paginator(qs.order_by(*order),60).get_page(request.GET.get('page'));rows=decorate(request,list(page.object_list),now)
    tiles=[(key,label,counts[key],hint) for key,label,hint in [('total','همه اعضا','هر شماره تأییدشده یک عضو'),('new','عضو جدید · ۷ روز','تاریخ عضویت'),('active','فعال · ۷ روز','ورود یا ذخیره اطلاعات؛ نه زمان حضور در اپ'),('program','برنامه فعال','برنامه غذایی فعال'),('visited','دارای مراجعه','حداقل یک مراجعه کرده یا انجام‌شده'),('unvisited','بدون مراجعه ثبت‌شده','شامل اعضای صرفاً استفاده‌کننده از اپ'),('attention','نیازمند رسیدگی','توضیح جدید، درخواست باز یا موعد پیگیری')]]
    trend=dict(CustomerPortalMember.objects.filter(created_at__gte=now-timedelta(days=29)).annotate(d=TruncDate('created_at')).values('d').annotate(n=Count('pk')).values_list('d','n'))
    days=[{'day':timezone.localdate()-timedelta(days=i),'n':trend.get(timezone.localdate()-timedelta(days=i),0)} for i in range(29,-1,-1)];peak=max([d['n'] for d in days]+[1])
    for d in days:d['height']=round(d['n']/peak*100)
    return private(request,'core/me_members.html',{'counts':counts,'tiles':tiles,'rows':rows,'page':page,'selected':selected,'q':q,'sort':sort,'query':urlencode({'group':selected,'q':q,'sort':sort}),'trend':days,'now':now})

def detail_context(request,pk,error='',notice=''):
    m=decorate(request,[get_object_or_404(members(),pk=pk)],timezone.now())[0]
    care=getattr(m,'me_care',None)
    meals=m.me_meals.order_by('-day','-updated_at')[:30]
    actions=m.me_actions.select_related('actor').all()[:50]
    team=[u for u in User.objects.filter(is_active=True).select_related('profile') if may_manage(u)]
    return {'action_kinds':MeMemberAction.KINDS,'member':m,'care':care,'meals':meals,'actions':actions,'requests':m.requests.select_related('branch').all()[:15], 'points':m.me_actions.aggregate(n=Sum('points'))['n'] or 0,'team':team,'token':uuid.uuid4(),'revision':care.revision if care else 0,'error':error,'notice':notice,'reviewed_through':timezone.now().isoformat()}

@gate
@require_http_methods(['GET','POST'])
def detail(request,pk):
    error='';notice='';status=200
    if request.method=='POST':
        try:
            token=uuid.UUID(request.POST.get('token',''));revision=int(request.POST.get('revision','-1'))
            kind=request.POST.get('kind');body=request.POST.get('body','').strip()
            if kind not in dict(MeMemberAction.KINDS) or len(body)>1000:raise ValueError('اطلاعات اقدام معتبر نیست.')
            if kind in ('reply','note','points') and not body:raise ValueError('متن یا دلیل را بنویسید.')
            points=int(request.POST.get('points') or 0) if kind=='points' else 0
            if kind=='points' and not 1<=points<=100:raise ValueError('امتیاز باید بین ۱ و ۱۰۰ باشد.')
            due=None;assignee=None
            if kind=='followup':
                raw=request.POST.get('followup_at','').strip()
                if raw and request.POST.get('followup_calendar') == 'jalali':
                    normalized=raw.translate(LATIN_DIGITS)
                    date_part,time_part=normalized.split()
                    day=parse_jalali(date_part)
                    if format_jalali(day,persian_digits=False) != date_part:
                        raise ValueError('تاریخ شمسی معتبر نیست.')
                    due=datetime.combine(day,datetime.strptime(time_part,'%H:%M').time())
                else:
                    due=parse_datetime(raw) if raw else None
                if raw and not due:raise ValueError('زمان پیگیری معتبر نیست.')
                if due and timezone.is_naive(due):due=timezone.make_aware(due)
                if due and due<=timezone.now():raise ValueError('زمان پیگیری باید در آینده باشد.')
                if request.POST.get('assigned_to'):
                    assignee=User.objects.filter(pk=request.POST['assigned_to']).first()
                    if not assignee or not may_manage(assignee):raise ValueError('مسئول مجاز را انتخاب کنید.')
            reviewed=parse_datetime(request.POST.get('reviewed_through',''))
            if kind in ('reply','review') and (not reviewed or timezone.is_naive(reviewed) or reviewed>timezone.now()):raise ValueError('صفحه را تازه‌سازی کنید.')
            with transaction.atomic():
                m=get_object_or_404(CustomerPortalMember.objects.select_for_update(),pk=pk)
                previous=MeMemberAction.objects.filter(token=token).first()
                if previous:
                    if previous.member_id!=m.pk or previous.actor_id!=request.user.pk:raise ValueError('شناسه تکراری معتبر نیست.')
                    notice='این اقدام قبلاً ثبت شده است.'
                else:
                    care,_=MeMemberCare.objects.get_or_create(member=m)
                    if care.revision!=revision:raise ValueError('اطلاعات توسط همکار دیگری تغییر کرده؛ دوباره بررسی کنید.')
                    if kind=='followup':
                        care.followup_at=due;care.assigned_to=assignee
                        body=('پیگیری: '+(timezone.localtime(due).strftime('%Y/%m/%d %H:%M') if due else 'لغو')+' · مسئول: '+(assignee.get_full_name() or assignee.username if assignee else 'تعیین نشده')+' · '+body)[:1000]
                    if kind in ('reply','review'):care.reviewed_at=reviewed;body=body or 'گزارش‌های موجود بررسی شد'
                    care.revision+=1;care.save()
                    MeMemberAction.objects.create(member=m,actor=request.user,kind=kind,body=body,points=points,token=token)
                    notice='ثبت شد؛ پاسخ و امتیاز در «پیام‌ها و امتیازهای من» عضو دیده می‌شوند.' if kind in ('reply','points') else 'اقدام داخلی ثبت شد.'
        except (ValueError,TypeError) as exc:error=str(exc) or 'اطلاعات معتبر نیست.';status=400
    context=detail_context(request,pk,error,notice)
    template='core/me_member_panel.html' if request.headers.get('X-Me-Panel')=='1' else 'core/me_member_detail.html'
    return private(request,template,context,status)

@require_GET
def inbox(request):
    m=_member(request)
    if not m:return redirect('/customer/login/?next=/customer/me/messages/')
    rows=m.me_actions.filter(kind__in=('reply','points')).select_related('actor')
    return private(request,'core/customer_portal/me_messages.html',{'page':Paginator(rows,30).get_page(request.GET.get('page')),'points':rows.aggregate(n=Sum('points'))['n'] or 0})
