import csv
import io
import os
import uuid
from collections import Counter
from datetime import timedelta
from functools import wraps
from urllib.parse import quote

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Count, Max, Q, Sum
from django.db.models.functions import TruncDate
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    PublicReferralLeadForm, BeytootePublicLeadForm, PersianBeautyPublicLeadForm, ReferralLeadForm, ReferralLeadManageForm,
    ReferralMemberForm, ReferralMemberEditForm, ReferralSaleForm, CallCenterLeadForm, CallCenterLeadCreateForm, CallCenterDirectLeadForm,
)
from .models import Attendance, AuditLog, CallCenterLeadGroup, ConsultationPlan, EmployeeProfile, ReferralLead, ReferralProfile, ReferralSale, StaffNotification, VisitAppointment, InternalMessage, DuplicateLeadError, PatientProfile, PersonalNotebookEntry
from .call_center_identity import FlowerLeadProxy, call_center_display_name
from .jalali import format_jalali, parse_jalali
# Production rebuild marker after the previous deployment hit the workflow timeout.


def _role(user):
    role=getattr(getattr(user, 'profile', None), 'role', 'employee')
    # Internal manager has full referral-management visibility, like system admin.
    return 'admin' if role=='internal_manager' else role


def referral_manager_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if _role(request.user) not in ('admin', 'manager'):
            messages.error(request, 'این بخش فقط برای مدیریت قابل دسترسی است.')
            return redirect('referral_dashboard')
        return view(request, *args, **kwargs)
    return wrapper


def referral_supervisor_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if _role(request.user)!='referral_supervisor':
            raise PermissionDenied('این صفحه فقط برای ناظر شبکه فروش قابل دسترسی است.')
        return view(request, *args, **kwargs)
    return wrapper


def _new_code():
    while True:
        code=f'GL{uuid.uuid4().hex[:8].upper()}'
        if not ReferralProfile.objects.filter(referral_code=code).exists():
            return code


def _ensure_profile(user):
    employee=getattr(user,'profile',None)
    if employee is not None and not getattr(employee,'sales_network_enabled',True):
        raise PermissionDenied('دسترسی شبکه فروش برای این کاربر غیرفعال است.')
    if _role(user)=='referral_supervisor':
        raise PermissionDenied('ناظر شبکه فروش فقط به داشبورد آماری دسترسی دارد.')
    if _role(user)=='call_center':
        raise PermissionDenied('دسترسی شبکه معرفی برای این نقش فعال نیست.')
    profile, _=ReferralProfile.objects.get_or_create(
        user=user,
        defaults={
            'referral_code':_new_code(),
            'phone':getattr(getattr(user, 'profile', None), 'phone', ''),
            'created_by':user,
        },
    )
    return ReferralProfile.objects.select_related(
        'user', 'user__profile', 'sponsor', 'sponsor__user', 'sponsor__sponsor'
    ).get(pk=profile.pk)


@referral_supervisor_required
def referral_supervisor_dashboard(request):
    """PII-free, read-only oversight for the referral-network supervisor."""
    today=timezone.localdate()
    month_start=today.replace(day=1)
    profiles=ReferralProfile.objects.filter(is_active=True).select_related(
        'user','user__profile','sponsor__user',
    )
    leads=ReferralLead.objects.filter(referrer__is_active=True)
    total_leads=leads.count()
    won_count=leads.filter(status='won').count()
    status_rows=[
        {'code':code,'label':label,'count':leads.filter(status=code).count()}
        for code,label in ReferralLead.STATUS
    ]
    def lead_origin(lead):
        if lead.group_id and lead.group.name:
            return lead.group.name
        source_url=(lead.source_url or '').lower()
        for marker,label in (
            ('/instagram/','اینستاگرام'),('/telegram/','تلگرام'),('/bale/','بله'),
            ('/beytoote/','بیتوته'),
        ):
            if marker in source_url:
                return label
        return lead.get_source_display()

    def masked_phone(value):
        value=value or ''
        if len(value)<8:
            return 'ثبت شده'
        return f'{value[:4]}***{value[-4:]}'

    origin_counts=Counter(
        lead_origin(lead)
        for lead in leads.select_related('group').only('source','source_url','group__name')
    )
    source_rows=[
        {'label':label,'count':count,'percent':round(count*100/max(1,total_leads))}
        for label,count in sorted(origin_counts.items(),key=lambda item:(-item[1],item[0]))
    ]
    member_rows=[]
    for profile in profiles.annotate(
        lead_count=Count('leads',distinct=True),
        won_count=Count('leads',filter=Q(leads__status='won'),distinct=True),
        open_count=Count('leads',filter=~Q(leads__status__in=('won','lost')),distinct=True),
        last_lead_at=Max('leads__created_at'),
    ).order_by('-lead_count','user__last_name','user__first_name'):
        member_rows.append({
            'name':profile.user.get_full_name() or profile.user.username,
            'branch':getattr(getattr(profile.user,'profile',None),'branch',None),
            'level':profile.level,
            'leads':profile.lead_count,
            'won':profile.won_count,
            'open':profile.open_count,
            'conversion':round(profile.won_count*100/max(1,profile.lead_count)),
            'last_activity':profile.last_lead_at,
        })
    daily_map={
        row['day']:row['count'] for row in
        leads.filter(created_at__date__gte=today-timezone.timedelta(days=29))
        .annotate(day=TruncDate('created_at')).values('day').annotate(count=Count('id'))
    }
    trend=[]
    max_daily=max([*daily_map.values(),1])
    for offset in range(29,-1,-1):
        day=today-timezone.timedelta(days=offset)
        count=daily_map.get(day,0)
        trend.append({
            'day':day,'count':count,'percent':round(count*100/max_daily),
            'show_label':offset % 5 == 0 or offset in (29,0),
        })
    recent_rows=[]
    for lead in leads.select_related('group','referrer__user').order_by('-created_at')[:20]:
        recent_rows.append({
            'phone':masked_phone(lead.phone),
            'origin':lead_origin(lead),
            'status':lead.get_status_display(),
            'status_code':lead.status,
            'referrer':lead.referrer.user.get_full_name() or lead.referrer.user.username,
            'created_at':lead.created_at,
        })
    return render(request,'core/referrals/supervisor_dashboard.html',{
        'member_count':profiles.count(),'total_leads':total_leads,
        'today_leads':leads.filter(created_at__date=today).count(),
        'month_leads':leads.filter(created_at__date__gte=month_start).count(),
        'won_count':won_count,'conversion_rate':round(won_count*100/max(1,total_leads)),
        'needs_action':leads.filter(
            Q(status__in=('new','contacted'))|Q(next_follow_up__lte=today)
        ).exclude(status__in=('won','lost')).distinct().count(),
        'status_rows':status_rows,'source_rows':source_rows,
        'member_rows':member_rows,'trend':trend,'recent_rows':recent_rows,
    })


def _subtree_ids(profile):
    direct=list(profile.members.filter(is_active=True).values_list('id', flat=True))
    second=list(ReferralProfile.objects.filter(sponsor_id__in=direct, is_active=True).values_list('id', flat=True))
    return [profile.id, *direct, *second]


def _manager_profiles(request):
    qs=ReferralProfile.objects.filter(is_active=True).select_related(
        'user', 'user__profile', 'sponsor', 'sponsor__user', 'sponsor__sponsor'
    )
    if _role(request.user)=='manager':
        branch_id=getattr(request.user.profile, 'branch_id', None)
        qs=qs.filter(
            Q(user__profile__branch_id=branch_id) |
            Q(sponsor__user__profile__branch_id=branch_id) |
            Q(sponsor__sponsor__user__profile__branch_id=branch_id)
        ).distinct()
    return qs


def _visible_profiles(request, current):
    if _role(request.user) in ('admin', 'manager'):
        return _manager_profiles(request)
    return ReferralProfile.objects.filter(pk__in=_subtree_ids(current)).select_related(
        'user', 'user__profile', 'sponsor', 'sponsor__user'
    )


def _root_branch(profile):
    root=profile
    while root.sponsor_id:
        root=root.sponsor
    return getattr(getattr(root.user, 'profile', None), 'branch', None)


def _photo_url(profile):
    image=profile.display_photo
    return image.url if image else ''


def _public_referral_url(profile):
    base=os.getenv('PUBLIC_BASE_URL','https://staff.greenlifeclinics.com').rstrip('/')
    return base+reverse('public_referral_lead',args=[profile.referral_code])


CALL_CENTER_STARTER_GROUPS=(
    ('شبکه فروش پرسنل',True),
    ('VIP',False),
    ('میزهای قدیمی دکتر جواهریان',False),
    ('وب‌سایت',False),
    ('کمپ',False),
    ('شرکت‌ها و همکاری سازمانی',False),
    ('اینستاگرام',False),
)


def _ensure_call_center_groups(operator=None):
    groups={}
    for name,is_default in CALL_CENTER_STARTER_GROUPS:
        group,_=CallCenterLeadGroup.objects.get_or_create(
            name=name,defaults={'owner':None,'is_default':is_default},
        )
        changed=[]
        if group.owner_id is not None:
            group.owner=None
            changed.append('owner')
        if is_default and not group.is_default:
            group.is_default=True
            changed.append('is_default')
        if changed:
            group.save(update_fields=changed)
        groups[name]=group
    return groups


def _default_call_center_group(operator=None):
    return _ensure_call_center_groups(operator)['شبکه فروش پرسنل']


def _can_manage_call_center_groups(user):
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    profile=getattr(user,'profile',None)
    if not profile:
        return False
    if profile.role in ('admin','internal_manager'):
        return True
    return bool(
        profile.role=='call_center'
        and getattr(profile,'can_manage_call_center_groups',False)
    )


def _call_center_direct_referrer():
    """Technical, inactive source for leads entered directly by call-center staff."""
    user,_=User.objects.get_or_create(
        username='call-center-direct-source',
        defaults={
            'first_name':'ثبت مستقیم','last_name':'کال‌سنتر','is_active':False,
        },
    )
    if user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=['password'])
    profile,_=ReferralProfile.objects.get_or_create(
        user=user,
        defaults={
            'referral_code':_new_code(),'is_active':False,'created_by':None,
        },
    )
    return profile


def _auto_assign_call_center(lead):
    """Route referral leads through the single production lead-routing policy."""
    from .lead_routing import assign_referral_lead
    return assign_referral_lead(lead)

def _notify_call_center_assignment(lead):
    if not lead.assigned_to_id:
        return
    StaffNotification.objects.create(
        user=lead.assigned_to.user,
        title='لید جدید برای تماس',
        message=f'{lead.full_name} با شماره {lead.phone} به صف پیگیری شما اضافه شد.',
        notification_type='call_center_lead',
        related_date=timezone.localdate(),
    )


@login_required
def referral_dashboard(request):
    current=_ensure_profile(request.user)
    is_manager=_role(request.user) in ('admin','manager')
    profiles=_visible_profiles(request, current)
    profile_ids=list(profiles.values_list('id', flat=True))
    leads=ReferralLead.objects.filter(referrer_id__in=profile_ids).select_related('referrer__user', 'assigned_to__user')
    sales=ReferralSale.objects.filter(lead__referrer_id__in=profile_ids).select_related('lead__referrer__user', 'lead__referrer__sponsor__user')
    approved=sales.filter(status__in=('approved', 'paid'))
    if _role(request.user) in ('admin', 'manager'):
        income=approved.aggregate(x=Sum('direct_commission')+Sum('level_two_commission'))['x'] or 0
    else:
        income=(
            ReferralSale.objects.filter(lead__referrer=current, status__in=('approved','paid')).aggregate(x=Sum('direct_commission'))['x'] or 0
        ) + (
            ReferralSale.objects.filter(lead__referrer__sponsor=current, status__in=('approved','paid')).aggregate(x=Sum('level_two_commission'))['x'] or 0
        )
    base_url=_public_referral_url(current)
    today=timezone.localdate()
    active_leads=leads.exclude(status__in=('won','lost'))
    followups=active_leads.filter(next_follow_up__lte=today).order_by('next_follow_up','created_at')
    pending_commission=sales.filter(status='approved').aggregate(
        x=Sum('direct_commission')+Sum('level_two_commission')
    )['x'] or 0
    context={
        'referral':current,'referral_link':base_url,'referral_qr':reverse('referral_qr',args=[current.referral_code]),
        'network_count':profiles.exclude(pk=current.pk).count(),'lead_count':leads.count(),
        'new_count':leads.filter(status='new').count(),'won_count':leads.filter(status='won').count(),
        'sales_total':approved.aggregate(x=Sum('amount'))['x'] or 0,'commission_total':income,
        'recent_leads':leads[:6],'recent_members':profiles.exclude(pk=current.pk)[:6],
        'can_add_member':current.level<2,'is_manager':is_manager,
        'today_count':leads.filter(created_at__date=today).count(),
        'action_count':active_leads.filter(Q(status__in=('new','contacted'))|Q(next_follow_up__lte=today)).distinct().count(),
        'followup_count':followups.count(),'recent_followups':followups[:5],
        'pending_commission':pending_commission,
        'conversion_rate':round(leads.filter(status='won').count()*100/max(1,leads.count())),
        'pipeline':{
            'new':leads.filter(status='new').count(),
            'contacted':leads.filter(status='contacted').count(),
            'appointment':leads.filter(status='appointment').count(),
            'visited':leads.filter(status='visited').count(),
            'won':leads.filter(status='won').count(),
        },
    }
    if is_manager:
        from public_network.models import PublicNetworkMember
        turkey_members=PublicNetworkMember.objects.filter(
            is_active=True,country__code='TR'
        ).select_related('user','sponsor__user','country').order_by('-created_at')
        turkey_leads=ReferralLead.objects.filter(
            country__code='TR'
        ).select_related('country','referrer__user','assigned_to__user').order_by('-created_at')
        context.update({
            'turkey_member_count':turkey_members.count(),
            'turkey_member_today':turkey_members.filter(created_at__date=today).count(),
            'turkey_lead_count':turkey_leads.count(),
            'turkey_lead_today':turkey_leads.filter(created_at__date=today).count(),
            'turkey_recent_members':turkey_members[:8],
            'turkey_recent_leads':turkey_leads[:8],
        })
    return render(request, 'core/referrals/dashboard.html', context)


@login_required
def referral_guide(request):
    if _role(request.user)=='call_center':
        raise PermissionDenied('دسترسی شبکه معرفی برای این نقش فعال نیست.')
    return render(request,'core/referrals/guide.html',{
        'is_manager':_role(request.user) in ('admin','manager'),
    })


@login_required
def referral_network(request):
    current=_ensure_profile(request.user)
    profiles=_visible_profiles(request,current)
    rows=[]
    for item in profiles.exclude(pk=current.pk):
        rows.append({
            'profile':item,'level':item.level,'photo':_photo_url(item),
            'leads':item.leads.count(),
            'won':item.leads.filter(status='won').count(),
            'sales':ReferralSale.objects.filter(lead__referrer=item,status__in=('approved','paid')).aggregate(x=Sum('amount'))['x'] or 0,
        })
    return render(request,'core/referrals/network.html',{
        'referral':current,'rows':rows,'can_add_member':current.level<2,
        'is_manager':_role(request.user) in ('admin','manager'),
    })


@login_required
def referral_member_create(request):
    current=_ensure_profile(request.user)
    allowed=_visible_profiles(request,current)
    sponsor_id=request.POST.get('sponsor') or request.GET.get('sponsor') or current.pk
    sponsor=get_object_or_404(allowed,pk=sponsor_id)
    if sponsor.level>=2:
        messages.error(request,'این فرد در سطح دوم است و امکان ساخت سطح سوم وجود ندارد.')
        return redirect('referral_network')
    form=ReferralMemberForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data
        with transaction.atomic():
            user=User.objects.create_user(
                username=d['username'],password=d['password'],first_name=d['first_name'],last_name=d['last_name']
            )
            EmployeeProfile.objects.update_or_create(user=user,defaults={
                'branch':_root_branch(sponsor),'role':'referrer','phone':d['phone'],
                'job_title':'معرف مشتری','is_active':True,
            })
            member=ReferralProfile.objects.create(
                user=user,sponsor=sponsor,referral_code=_new_code(),phone=d['phone'],
                photo=d.get('photo'),created_by=request.user,
            )
        try:
            from .sms_automation import queue_network_welcome_sms
            sms_status=queue_network_welcome_sms(member,initial_password=d['password'])
        except Exception:
            sms_status='queue_error'
        public_base=os.getenv('PUBLIC_BASE_URL','https://staff.greenlifeclinics.com').rstrip('/')
        login_url=f'{public_base}{reverse("login")}'
        full_name=user.get_full_name() or user.username
        from .network_whatsapp import SALES_NETWORK_WHATSAPP_URL
        invite_text=(
            f'سلام {full_name}\n'
            'عضویت شما در شبکه فروش گرین‌لایف فعال شد.\n\n'
            f'نام کاربری: {user.username}\n'
            f'رمز ورود: {d["password"]}\n'
            f'لینک ورود: {login_url}\n\n'
            f'گروه واتساپ شبکه فروش (اختیاری): {SALES_NETWORK_WHATSAPP_URL}\\n'
            'لطفاً این اطلاعات را محرمانه نگه دارید.'
        )
        phone=''.join(ch for ch in d['phone'] if ch.isdigit())
        if phone.startswith('0'):
            phone='98'+phone[1:]
        elif not phone.startswith('98'):
            phone='98'+phone
        whatsapp_url=f'https://wa.me/{phone}?text={quote(invite_text)}'
        return render(request,'core/referrals/member_invite.html',{
            'member':member,'plain_password':d['password'],'login_url':login_url,
            'invite_text':invite_text,'whatsapp_url':whatsapp_url,
            'sms_status':sms_status,'sales_whatsapp_url':SALES_NETWORK_WHATSAPP_URL,
        })
    return render(request,'core/referrals/form.html',{
        'form':form,'title':'افزودن عضو شبکه','subtitle':f'زیرمجموعه {sponsor}',
        'button':'ساخت حساب معرف','sponsor':sponsor,
    })




@login_required
def referral_member_edit(request,pk):
    if _role(request.user) not in ('admin','manager'):
        raise PermissionDenied('ویرایش عضو فقط برای مدیریت مجاز است.')
    current=_ensure_profile(request.user)
    member=get_object_or_404(_visible_profiles(request,current),pk=pk,user__profile__role='referrer')
    initial={'first_name':member.user.first_name,'last_name':member.user.last_name,
             'phone':member.phone,'username':member.user.username}
    form=ReferralMemberEditForm(request.POST or None,member=member,initial=initial)
    if request.method=='POST' and form.is_valid():
        data=form.cleaned_data
        with transaction.atomic():
            member.user.first_name=data['first_name']
            member.user.last_name=data['last_name']
            member.user.username=data['username']
            changed_password=data.get('new_password')
            if changed_password:
                member.user.set_password(changed_password)
            member.user.save()
            member.phone=data['phone']
            member.save(update_fields=['phone'])
            EmployeeProfile.objects.filter(user=member.user).update(phone=data['phone'])
        if changed_password:
            try:
                from .sms_automation import queue_network_welcome_sms
                queue_network_welcome_sms(member,resend=True,initial_password=changed_password)
            except Exception:
                messages.warning(request,'رمز ذخیره شد، اما ارسال پیامک آن تأیید نشد.')
        messages.success(request,'اطلاعات عضو ذخیره شد.' + (' رمز ورود نیز تغییر کرد.' if changed_password else ''))
        return redirect('referral_network')
    return render(request,'core/referrals/member_edit.html',{'form':form,'member':member})


@login_required
def referral_member_custom_sms(request,pk):
    if request.method!='POST':
        return HttpResponse(status=405)
    if _role(request.user) not in ('admin','manager'):
        raise PermissionDenied('ارسال پیامک فقط برای مدیریت مجاز است.')
    current=_ensure_profile(request.user)
    member=get_object_or_404(_visible_profiles(request,current),pk=pk,user__profile__role='referrer')
    body=(request.POST.get('body') or '').strip()
    if not body or len(body)>600:
        messages.error(request,'متن پیامک باید بین ۱ تا ۶۰۰ نویسه باشد.')
        return redirect('referral_network')
    try:
        from .sms import send_sms
        send_sms(member.phone,body,purpose='manual',created_by=request.user)
    except Exception:
        messages.error(request,'ارسال پیامک موفق نبود. تنظیمات API و شماره موبایل را بررسی کنید.')
    else:
        messages.success(request,'پیامک برای ارسال به درگاه تحویل داده شد.')
    return redirect('referral_network')


@login_required
def referral_member_sms_resend(request,pk):
    """Manual retry for previously registered members; managers only."""
    if request.method!='POST':
        return HttpResponse(status=405)
    if _role(request.user) not in ('admin','manager'):
        raise PermissionDenied('ارسال پیامک عضویت فقط برای مدیریت مجاز است.')
    current=_ensure_profile(request.user)
    member=get_object_or_404(_visible_profiles(request,current),pk=pk,user__profile__role='referrer')
    try:
        from .sms_automation import queue_network_welcome_sms
        state=queue_network_welcome_sms(member,resend=True)
    except Exception:
        state='queue_error'
    if state=='queued':
        messages.success(request,'پیامک حاوی لینک ورود عضو در صف ارسال قرار گرفت؛ وضعیت را در مدیریت پیامک ببینید.')
    elif state in ('already_queued','recently_sent'):
        messages.info(request,'پیامک این عضو قبلاً در صف بوده یا طی ۵ دقیقه اخیر ارسال شده است.')
    elif state=='gateway_unavailable':
        messages.warning(request,'سرویس پیامک REST API هنوز فعال یا پیکربندی نشده؛ لینک را از واتساپ بفرستید.')
    elif state=='invalid_phone':
        messages.error(request,'شماره موبایل عضو برای ارسال پیامک ایران معتبر نیست.')
    elif state=='rule_disabled':
        messages.warning(request,'قانون پیامک خوشامدگویی شبکه فروش غیرفعال است.')
    else:
        messages.error(request,'ثبت درخواست پیامک موفق نبود؛ عضویت عضو تغییری نکرد.')
    return redirect('referral_network')


@login_required
def referral_lead_list(request):
    current=_ensure_profile(request.user)
    profile_ids=_visible_profiles(request,current).values_list('id',flat=True)
    leads=ReferralLead.objects.filter(referrer_id__in=profile_ids).select_related(
        'referrer__user','assigned_to__user'
    )
    status=request.GET.get('status','')
    if status in dict(ReferralLead.STATUS): leads=leads.filter(status=status)
    return render(request,'core/referrals/leads.html',{
        'referral':current,'leads':leads,'status_filter':status,
        'statuses':ReferralLead.STATUS,'is_manager':_role(request.user) in ('admin','manager'),
    })


@login_required
def referral_lead_create(request):
    current=_ensure_profile(request.user)
    allowed=_visible_profiles(request,current)
    referrer_id=request.POST.get('referrer') or request.GET.get('referrer') or current.pk
    referrer=get_object_or_404(allowed,pk=referrer_id)
    form=ReferralLeadForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        lead=form.save(commit=False); lead.referrer=referrer; lead.source='panel'; lead.created_by=request.user; lead.save()
        assigned=_auto_assign_call_center(lead)
        if assigned:
            operator_name=assigned.user.get_full_name() or assigned.user.username
            group_name=lead.group.name if lead.group_id else 'بدون گروه'
            messages.success(
                request,
                f'لید ثبت شد؛ به کال‌سنتر، اپراتور «{operator_name}» و گروه «{group_name}» ارسال شد.'
            )
        else:
            messages.warning(
                request,
                'لید ثبت شد، اما اپراتور فعال کال‌سنتر پیدا نشد؛ لید در صف بدون مسئول باقی مانده است.'
            )
        return redirect('referral_lead_list')
    return render(request,'core/referrals/form.html',{
        'form':form,'title':'ثبت لید جدید','subtitle':f'معرف: {referrer}',
        'button':'ثبت مشتری','referrer':referrer,
    })


def _greenlife_qr_source():
    """Technical Green Life source for public QR leads; never shown as a person."""
    user,_=User.objects.get_or_create(
        username='greenlife-public-qr-source',
        defaults={
            'first_name':'Green Life','last_name':'','is_active':False,
        },
    )
    if user.has_usable_password():
        user.set_unusable_password()
        user.save(update_fields=['password'])
    profile,_=ReferralProfile.objects.get_or_create(
        user=user,
        defaults={
            'referral_code':_new_code(),
            'is_active':False,
            'created_by':None,
        },
    )
    if profile.is_active:
        profile.is_active=False
        profile.save(update_fields=['is_active','updated_at'])
    return profile


def public_admin_qr_lead(request):
    """Public Green Life QR form. Leads stay unassigned for central review."""
    referrer=_greenlife_qr_source()
    form=PublicReferralLeadForm(request.POST or None)
    completed=False
    if request.method=='POST' and form.is_valid():
        lead=form.save(commit=False)
        lead.referrer=referrer
        lead.source='qr'
        lead.source_url=request.build_absolute_uri()[:500]
        lead.assigned_to=None
        lead.group=None
        lead.created_by=None
        lead.save()
        completed=True
        form=PublicReferralLeadForm()
    return render(request,'core/referrals/public_lead.html',{
        'form':form,'referrer':referrer,'completed':completed,'photo':'',
        'show_referrer':False,
        'page_title':'مشاوره لاغری رایگان | Green Life',
        'headline':'مشاوره لاغری رایگان',
        'intro':'اطلاعاتتان را ثبت کنید تا کارشناسان گرین‌لایف برای مشاوره رایگان با شما تماس بگیرند.',
        'submit_label':'ثبت درخواست مشاوره رایگان',
    })


def public_beytoote_lead(request):
    """Simplified public landing form dedicated to Beytoote campaign traffic."""
    referrer=_greenlife_qr_source()
    form=BeytootePublicLeadForm(request.POST or None)
    completed=False
    if request.method=='POST' and form.is_valid():
        lead=form.save(commit=False)
        lead.referrer=referrer
        lead.source='link'
        lead.source_url=request.build_absolute_uri()[:500]
        lead.assigned_to=None
        lead.group=None
        lead.created_by=None
        lead.save()
        completed=True
        form=BeytootePublicLeadForm()
    return render(request,'core/referrals/public_lead.html',{
        'form':form,'referrer':referrer,'completed':completed,'photo':'',
        'show_referrer':False,
        'page_title':'مشاوره لاغری رایگان | Green Life',
        'headline':'مشاوره رایگان لاغری',
        'intro':'نام و شماره موبایل خود را ثبت کنید و اگر دوست دارید، ناحیه یا دغدغه اصلی‌تان را هم کوتاه توضیح دهید.',
        'submit_label':'ثبت درخواست مشاوره رایگان',
        'body_class':'rf-beytoote',
        'footer_text':'اطلاعات شما فقط برای پیگیری درخواست مشاوره استفاده می‌شود.',
    })


def public_persian_beauty_lead(request):
    """Minimal public landing form dedicated to Persian Beauty traffic."""
    referrer=_greenlife_qr_source()
    form=PersianBeautyPublicLeadForm(request.POST or None)
    completed=False
    if request.method=='POST' and form.is_valid():
        lead=form.save(commit=False)
        lead.referrer=referrer
        lead.source='link'
        lead.source_url=request.build_absolute_uri()[:500]
        lead.notes='[channel:persian_beauty] | [source:Persian Beauty]'
        lead.assigned_to=None
        lead.group=None
        lead.created_by=None
        lead.save()
        completed=True
        form=PersianBeautyPublicLeadForm()
    return render(request,'core/referrals/public_lead.html',{
        'form':form,'referrer':referrer,'completed':completed,'photo':'',
        'show_referrer':False,
        'page_title':'مشاوره رایگان | Green Life × Persian Beauty',
        'headline':'درخواست مشاوره رایگان',
        'intro':'نام و شماره موبایل خود را ثبت کنید تا کارشناسان گرین‌لایف با شما تماس بگیرند.',
        'submit_label':'ثبت درخواست',
        'body_class':'rf-beytoote rf-persian-beauty',
        'footer_text':'اطلاعات شما فقط برای پیگیری درخواست مشاوره استفاده می‌شود.',
    })


def public_aparat_lead(request):
    """Simplified public landing form dedicated to Aparat campaign traffic."""
    referrer=_greenlife_qr_source()
    form=BeytootePublicLeadForm(request.POST or None)
    completed=False
    if request.method=='POST' and form.is_valid():
        lead=form.save(commit=False)
        lead.referrer=referrer
        lead.source='link'
        lead.source_url=request.build_absolute_uri()[:500]
        lead.assigned_to=None
        lead.group=None
        lead.created_by=None
        lead.save()
        completed=True
        form=BeytootePublicLeadForm()
    return render(request,'core/referrals/public_lead.html',{
        'form':form,'referrer':referrer,'completed':completed,'photo':'',
        'show_referrer':False,
        'page_title':'مشاوره لاغری رایگان | Green Life',
        'headline':'مشاوره رایگان لاغری',
        'intro':'نام و شماره موبایل خود را ثبت کنید و اگر دوست دارید، ناحیه یا دغدغه اصلی‌تان را هم کوتاه توضیح دهید.',
        'submit_label':'ثبت درخواست مشاوره رایگان',
        'body_class':'rf-beytoote',
        'footer_text':'اطلاعات شما فقط برای پیگیری درخواست مشاوره استفاده می‌شود.',
    })


def public_referral_lead(request,code):
    referrer=get_object_or_404(ReferralProfile.objects.select_related('user'),referral_code=code,is_active=True)
    form=PublicReferralLeadForm(request.POST or None)
    completed=False
    if request.method=='POST' and form.is_valid():
        lead=form.save(commit=False); lead.referrer=referrer
        lead.source='qr' if request.GET.get('src')=='qr' else 'link'
        lead.source_url=request.build_absolute_uri()[:500]
        lead.save(); _auto_assign_call_center(lead); completed=True; form=PublicReferralLeadForm()
    return render(request,'core/referrals/public_lead.html',{
        'form':form,'referrer':referrer,'completed':completed,'photo':_photo_url(referrer),
        'show_referrer':True,
    })


def referral_qr(request,code):
    referrer=get_object_or_404(ReferralProfile,referral_code=code,is_active=True)
    try:
        import qrcode
    except ImportError:
        return HttpResponse('QR service unavailable',status=503,content_type='text/plain')
    target=_public_referral_url(referrer)+'?src=qr'
    qr=qrcode.QRCode(version=None,box_size=10,border=3,error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(target); qr.make(fit=True)
    image=qr.make_image(fill_color='#142c24',back_color='white')
    buffer=io.BytesIO(); image.save(buffer,format='PNG')
    response=HttpResponse(buffer.getvalue(),content_type='image/png')
    response['Content-Disposition']=f'inline; filename="greenlife-{referrer.referral_code}.png"'
    response['Cache-Control']='public, max-age=3600'
    return response


@referral_manager_required
def referral_lead_manage(request,pk):
    current=_ensure_profile(request.user)
    allowed_ids=_visible_profiles(request,current).values_list('id',flat=True)
    lead=get_object_or_404(ReferralLead.objects.select_related('referrer__user'),pk=pk,referrer_id__in=allowed_ids)
    branch=request.user.profile.branch if _role(request.user)=='manager' else None
    form=ReferralLeadManageForm(request.POST or None,instance=lead,branch=branch)
    if request.method=='POST' and form.is_valid():
        previous_assignee=lead.assigned_to_id
        updated=form.save()
        if updated.assigned_to_id!=previous_assignee:
            if updated.assigned_to_id:
                updated.group=_default_call_center_group(updated.assigned_to)
                updated.save(update_fields=['group','updated_at'])
                _notify_call_center_assignment(updated)
            elif updated.group_id:
                updated.group=None
                updated.save(update_fields=['group','updated_at'])
        messages.success(request,'وضعیت پیگیری لید به‌روزرسانی شد.')
        return redirect('referral_lead_list')
    return render(request,'core/referrals/form.html',{
        'form':form,'title':f'پیگیری {lead.full_name}','subtitle':f'{lead.phone} · معرف: {lead.referrer}',
        'button':'ذخیره پیگیری','lead':lead,
    })


def _call_center_appointment_journey(item):
    """Derive the live patient journey from the existing receptionist/doctor/consultant/payment state."""
    plan=None
    try:
        plan=item.consultation_plan
    except ConsultationPlan.DoesNotExist:
        plan=None

    changed_at=item.updated_at
    source='سیستم'
    key='booked'
    label='نوبت ثبت شده'
    needs_call=False

    if item.status=='cancelled':
        key,label,source='cancelled','لغو شده','منشی'
    elif item.status=='no_show':
        key,label,source,needs_call='no_show','عدم مراجعه','منشی',True
    elif plan and plan.status=='paid':
        key,label,source='sale_success','فروش موفق','مالی / منشی'
        changed_at=plan.paid_at or plan.updated_at
    elif plan and plan.status=='no_sale':
        key,label,source,needs_call='sale_lost','خرید نکرد · پیگیری لازم','مشاور',True
        changed_at=plan.updated_at
    elif item.lead_id and item.lead.status=='won':
        key,label,source='sale_success','فروش موفق','فروش'
        changed_at=item.lead.updated_at
    elif plan and plan.status=='partial_paid':
        key,label,source='partial_paid','بیعانه ثبت شد · در انتظار تسویه','مالی / منشی'
        changed_at=plan.updated_at
    elif item.lead_id and item.lead.status=='lost':
        key,label,source,needs_call='sale_lost','فروش ناموفق · پیگیری لازم','کال‌سنتر / مشاور',True
        changed_at=item.lead.updated_at
    elif item.status=='completed' or item.care_stage=='closed':
        key,label,source='completed','مراجعه تکمیل شد','منشی'
    elif (plan and plan.status in ('payment_pending','finalized')) or item.care_stage=='payment':
        key,label,source='payment','مشاوره انجام شد · در انتظار پرداخت','مشاور'
        if plan:
            changed_at=plan.updated_at
    elif item.status=='arrived' and item.care_stage=='consultant':
        key,label,source='consultant','ویزیت پزشک انجام شد · نزد مشاور','پزشک'
        changed_at=item.doctor_completed_at or item.updated_at
    elif item.status=='arrived' and item.care_stage=='doctor':
        key,label,source='doctor','پذیرش منشی · در انتظار پزشک','منشی'
    elif item.status=='arrived':
        key,label,source='arrived','مراجعه کرد · پذیرش شد','منشی'
    elif item.status=='booked':
        key,label='booked','نوبت ثبت شده'
        source='کال‌سنتر' if item.source=='call_center' else ('منشی' if item.source=='receptionist' else 'مدیریت')
        changed_at=item.created_at

    local_changed=timezone.localtime(changed_at) if changed_at else None
    return {
        'key':key,
        'label':label,
        'source':source,
        'changed_at':local_changed,
        'changed_time':local_changed.strftime('%H:%M') if local_changed else '—',
        'needs_call':needs_call,
    }


def call_center_required(view):
    @wraps(view)
    @login_required
    def wrapper(request,*args,**kwargs):
        if _role(request.user)!='call_center':
            messages.error(request,'این بخش فقط برای کارشناسان کال‌سنتر قابل دسترسی است.')
            return redirect('dashboard')
        return view(request,*args,**kwargs)
    return wrapper


@call_center_required
def call_center_dashboard(request):
    operator=request.user.profile
    from .lead_routing import operator_policy_notice, eligible_operator_user_ids
    routing_policy_notice=operator_policy_notice(operator)
    default_group=_default_call_center_group(operator)
    ReferralLead.objects.filter(assigned_to=operator,group__isnull=True).update(group=default_group)
    all_leads=ReferralLead.objects.filter(assigned_to=operator)
    leads=all_leads.select_related('country','assigned_to','group','referrer__user','created_by')
    status=request.GET.get('status','')
    if status in dict(ReferralLead.STATUS):
        leads=leads.filter(status=status)

    group_filter=(request.GET.get('group') or '').strip()
    if group_filter=='ungrouped':
        leads=leads.filter(group__isnull=True)
    elif group_filter.isdigit():
        leads=leads.filter(group_id=int(group_filter))

    today=timezone.localdate()
    tomorrow=today+timedelta(days=1)

    # Date-driven daily agenda keeps scheduled callbacks visible on the day
    # they are due, regardless of how old the original lead is.
    agenda_due=list(
        all_leads
        .filter(next_follow_up__lte=today)
        .exclude(status__in=('won','lost'))
        .select_related('country','assigned_to','group','referrer__user','created_by')
        .order_by('-next_follow_up','updated_at','id')
    )
    agenda_today_count=sum(1 for lead in agenda_due if lead.next_follow_up==today)
    agenda_overdue_count=len(agenda_due)-agenda_today_count

    tomorrow_appointments=(
        VisitAppointment.objects.filter(appointment_date=tomorrow)
        .filter(Q(lead__assigned_to=operator) | Q(created_by=request.user,source='call_center'))
        .exclude(status='cancelled')
        .select_related('branch','lead')
        .order_by('appointment_time','id')
        .distinct()
    )

    # Operator Cockpit is intentionally computed from existing records only:
    # no migration and no change to the lead-distribution engine is required.
    local_now=timezone.localtime()
    attendance=Attendance.objects.filter(user=request.user,date=today).first()
    eligible_today=request.user.pk in eligible_operator_user_ids(today)
    if attendance and attendance.check_in and not attendance.check_out and eligible_today:
        routing_state='active'
        routing_state_label='در چرخه دریافت لید هستید'
        routing_state_reason='حضور فعال'
    elif attendance and attendance.check_out:
        routing_state='out'
        routing_state_label='خارج از چرخه دریافت لید'
        routing_state_reason='خروج ثبت شده'
    elif attendance and attendance.check_in:
        routing_state='out'
        routing_state_label='خارج از چرخه دریافت لید'
        routing_state_reason='امروز برای توزیع لید فعال نیستید'
    else:
        routing_state='out'
        routing_state_label='خارج از چرخه دریافت لید'
        routing_state_reason='حضور ثبت نشده'
    shift_started_at=(
        timezone.localtime(attendance.check_in).strftime('%H:%M')
        if attendance and attendance.check_in else '—'
    )

    result_today=all_leads.filter(updated_at__date=today).exclude(contact_result='')
    calls_today=result_today.count()
    answered_today=result_today.exclude(contact_result='no_answer').count()
    response_rate=round(answered_today*100/max(1,calls_today))
    appointments_created_today=(
        VisitAppointment.objects.filter(
            source='call_center',created_by=request.user,created_at__date=today,
        )
        .exclude(status='cancelled')
        .exclude(lead__isnull=True)
        .values('lead_id').distinct().count()
    )
    today_sales_qs=ReferralSale.objects.filter(
        lead__assigned_to=operator,sale_date=today,status__in=('approved','paid')
    )
    today_sales_count=today_sales_qs.count()
    today_sales_amount=today_sales_qs.aggregate(x=Sum('amount'))['x'] or 0

    queue_scope=all_leads
    if group_filter=='ungrouped':
        queue_scope=queue_scope.filter(group__isnull=True)
    elif group_filter.isdigit():
        queue_scope=queue_scope.filter(group_id=int(group_filter))

    queue_candidates=list(
        queue_scope
        .exclude(status__in=('won','lost'))
        .filter(
            Q(status='new') |
            Q(next_follow_up__lte=today) |
            Q(contact_result='no_answer') |
            Q(status='appointment')
        )
        .select_related('country','assigned_to','group','referrer__user','created_by')
        .order_by('assigned_at','created_at','id')[:250]
    )

    def _wa_url(phone):
        digits=''.join(ch for ch in str(phone or '') if ch.isdigit())
        if digits.startswith('0098'):
            digits=digits[2:]
        if digits.startswith('09') and len(digits)==11:
            digits='98'+digits[1:]
        elif digits.startswith('9') and len(digits)==10:
            digits='98'+digits
        elif digits.startswith('0') and len(digits)>10:
            digits=digits[1:]
        return f'https://wa.me/{digits}' if 10 <= len(digits) <= 15 else ''

    def _source_key(label,lead):
        text=(str(label or '')+' '+str(getattr(lead,'source_url','') or '')+' '+str(getattr(lead,'notes','') or '')).lower()
        if 'instagram' in text or 'اینستاگرام' in text:
            return 'instagram'
        if 'beytoote' in text or 'بیتوته' in text:
            return 'beytoote'
        if 'whatsapp' in text or 'واتس' in text or 'wa.me' in text:
            return 'whatsapp'
        if 'greenlifeclinics.com' in text or 'website' in text or 'وب' in text:
            return 'website'
        group_name=str(getattr(getattr(lead,'group',None),'name','') or '')
        if 'شبکه فروش' in group_name or 'معرف' in group_name:
            return 'network'
        return 'other'

    work_queue=[]
    category_counts={key:0 for key in ('all','new','todaycall','followup','appointment','noanswer','overdue')}
    for lead in queue_candidates:
        proxy=FlowerLeadProxy(lead)
        assigned_at=lead.assigned_at or lead.created_at
        assigned_local=timezone.localtime(assigned_at)
        age_minutes=max(0,int((local_now-assigned_local).total_seconds()//60))
        categories=[]
        is_overdue=bool(lead.next_follow_up and lead.next_follow_up<today)
        if lead.status=='new':
            categories.append('new')
        if lead.next_follow_up==today:
            categories.extend(['todaycall','followup'])
        elif lead.contact_result=='follow_up':
            categories.append('followup')
        if lead.status=='appointment' or lead.contact_result=='appointment':
            categories.append('appointment')
        if lead.contact_result=='no_answer':
            categories.append('noanswer')
        if is_overdue or (lead.status=='new' and not lead.contact_result and age_minutes>=60):
            categories.append('overdue')
        categories=list(dict.fromkeys(categories))

        if is_overdue:
            sla_label='پیگیری عقب‌افتاده'
            sla_class='red'
            priority=0
        elif lead.next_follow_up==today:
            sla_label='موعد امروز'
            sla_class='amber'
            priority=1
        elif lead.status=='new' and not lead.contact_result:
            if age_minutes<30:
                sla_label=f'{age_minutes} دقیقه'
                sla_class='green'
                priority=2
            elif age_minutes<60:
                sla_label=f'{age_minutes} دقیقه'
                sla_class='amber'
                priority=2
            else:
                hours,minutes=divmod(age_minutes,60)
                sla_label=(f'{hours}س {minutes}د عقب‌افتاده' if hours else f'{minutes} دقیقه عقب‌افتاده')
                sla_class='red'
                priority=0
        else:
            sla_label='اقدام ثبت شده'
            sla_class='neutral'
            priority=4

        if lead.next_follow_up and lead.next_follow_up<=today:
            next_action='تماس پیگیری'
        elif lead.status=='new':
            next_action='تماس اولیه'
        elif lead.contact_result=='no_answer':
            next_action='تماس مجدد'
        elif lead.status=='appointment':
            next_action='پیگیری نوبت'
        else:
            next_action='بررسی پرونده'

        if lead.contact_result:
            last_action=lead.get_contact_result_display()
        elif lead.status=='new':
            last_action='هنوز نتیجه‌ای ثبت نشده'
        else:
            # Use the call-center wording layer so identical business states
            # never appear with two different labels (e.g. appointment).
            last_action=proxy.get_status_display()

        source_label=proxy.source_page_display or proxy.source_origin_display
        work_queue.append({
            'lead':proxy,
            'categories':' '.join(categories),
            'source_label':source_label,
            'source_key':_source_key(source_label,lead),
            'received_at':assigned_local,
            'received_day':assigned_local.date(),
            'sla_label':sla_label,
            'sla_class':sla_class,
            'last_action':last_action,
            'last_action_at':timezone.localtime(lead.updated_at),
            'next_action':next_action,
            'wa_url':_wa_url(lead.phone),
            '_sort':(priority,assigned_local),
        })
        category_counts['all']+=1
        for key in categories:
            if key in category_counts:
                category_counts[key]+=1
    work_queue.sort(key=lambda item:item['_sort'])
    for item in work_queue:
        item.pop('_sort',None)

    next_queue=work_queue[:5]
    upcoming_followups=list(
        all_leads.filter(next_follow_up__gt=today,next_follow_up__lte=today+timedelta(days=3))
        .exclude(status__in=('won','lost'))
        .select_related('group')
        .order_by('next_follow_up','updated_at')[:5]
    )
    cockpit={
        'routing_state':routing_state,
        'routing_state_label':routing_state_label,
        'routing_state_reason':routing_state_reason,
        'shift_started_at':shift_started_at,
        'calls_today':calls_today,
        'response_rate':response_rate,
        'appointments_created_today':appointments_created_today,
        'today_sales_count':today_sales_count,
        'today_sales_million':round(float(today_sales_amount)/1_000_000,1),
    }

    month_start=today.replace(day=1)
    today_leads=all_leads.filter(created_at__date=today)
    month_leads=all_leads.filter(created_at__date__gte=month_start)
    month_total=month_leads.count()
    month_handled=month_leads.exclude(status='new').count()
    month_appointments=(
        VisitAppointment.objects.filter(
            lead__assigned_to=operator,
            source='call_center',
            created_by=request.user,
            created_at__date__gte=month_start,
        )
        .exclude(status='cancelled')
        .exclude(lead__isnull=True)
        .values('lead_id').distinct().count()
    )
    month_visits=(
        VisitAppointment.objects.filter(
            lead__assigned_to=operator,
            source='call_center',
            created_by=request.user,
            appointment_date__gte=month_start,
            appointment_date__lte=today,
            status__in=('arrived','completed'),
        )
        .exclude(lead__isnull=True)
        .values('lead_id').distinct().count()
    )
    month_won=month_leads.filter(status='won').count()
    month_sales=(
        ReferralSale.objects.filter(
            lead__assigned_to=operator,
            sale_date__gte=month_start,
            status__in=('approved','paid'),
        ).aggregate(x=Sum('amount'))['x'] or 0
    )
    team_today=ReferralLead.objects.filter(
        assigned_to__role='call_center',
        assigned_to__is_active=True,
        assigned_to__user__is_active=True,
        created_at__date=today,
    ).count()
    performance={
        'today_uncontacted':today_leads.filter(status='new').count(),
        'today_handled':today_leads.exclude(status='new').count(),
        'team_today':team_today,
        'lead_share_today':round(today_leads.count()*100/max(1,team_today)),
        'month_total':month_total,
        'month_handled':month_handled,
        'care_rate':round(month_handled*100/max(1,month_total)),
        'month_appointments':month_appointments,
        'appointment_rate':round(month_appointments*100/max(1,month_total)),
        'month_visits':month_visits,
        'visit_rate':round(month_visits*100/max(1,month_appointments)),
        'month_won':month_won,
        'conversion_rate':round(month_won*100/max(1,month_total)),
        'sales_million':round(float(month_sales)/1_000_000,1),
        'overdue':all_leads.filter(
            status__in=('new','contacted','appointment'),
            next_follow_up__lt=today,
        ).count(),
    }
    groups=(CallCenterLeadGroup.objects.all()
            .annotate(lead_count=Count('leads',filter=Q(leads__assigned_to=operator)))
            .order_by('-is_default','name','id'))
    stats={
        'all':all_leads.count(),
        'today':today_leads.count(),
        'new':all_leads.filter(status='new').count(),
        'follow_up':all_leads.filter(next_follow_up__lte=today).exclude(status__in=('won','lost')).count(),
        'appointment':VisitAppointment.objects.filter(
            lead__assigned_to=operator,appointment_date__gte=today
        ).exclude(status='cancelled').count(),
        'appointment_today':VisitAppointment.objects.filter(
            lead__assigned_to=operator,appointment_date=today
        ).exclude(status='cancelled').count(),
        'ungrouped':all_leads.filter(group__isnull=True).count(),
    }
    today_appointments=list(
        VisitAppointment.objects.filter(
            appointment_date=today,
            lead__assigned_to=operator,
        )
        .select_related('branch','lead','consultation_plan','consultation_plan__consultant')
        .order_by('appointment_time','id')[:12]
    )
    for item in today_appointments:
        journey=_call_center_appointment_journey(item)
        item.journey_key=journey['key']
        item.journey_label=journey['label']
        item.journey_source=journey['source']
        item.journey_changed_time=journey['changed_time']
        item.journey_needs_call=journey['needs_call']

    appointment_by_time={
        item.appointment_time.strftime('%H:%M'):item for item in today_appointments
    }
    appointment_slots=[]
    for hour in range(9,19):
        minutes=(0,15,30,45) if hour<18 else (0,)
        for minute in minutes:
            label=f'{hour:02d}:{minute:02d}'
            appointment_slots.append({
                'label':label,
                'appointment':appointment_by_time.get(label),
            })
    recent_internal_messages=(
        InternalMessage.objects.filter(
            Q(recipient__isnull=True) | Q(sender=request.user) | Q(recipient=request.user)
        )
        .select_related('sender','sender__profile','recipient','recipient__profile')
        .order_by('-created_at')[:6]
    )
    internal_unread=InternalMessage.objects.filter(
        recipient=request.user,read_at__isnull=True
    ).count()
    chat_contacts=list(
        User.objects.filter(is_active=True,profile__is_active=True)
        .exclude(pk=request.user.pk)
        .exclude(profile__role='referrer')
        .select_related('profile','profile__branch')
        .order_by('profile__branch__name','first_name','last_name','username')
    )
    transfer_operators=[
        {'id':profile.pk,'name':call_center_display_name(profile)}
        for profile in EmployeeProfile.objects.filter(
            role='call_center',is_active=True,user__is_active=True,
        ).exclude(pk=operator.pk).select_related('user')
    ]
    transfer_operators.sort(key=lambda item:item['name'])
    return render(request,'core/call_center/dashboard.html',{
        'leads':[FlowerLeadProxy(lead) for lead in leads],'statuses':ReferralLead.STATUS,'status_filter':status,
        'group_filter':group_filter,'groups':groups,
        'stats':stats,'performance':performance,'today':today,'tomorrow':tomorrow,
        'agenda_due':[FlowerLeadProxy(lead) for lead in agenda_due],
        'agenda_today_count':agenda_today_count,'agenda_overdue_count':agenda_overdue_count,
        'tomorrow_appointments':tomorrow_appointments,
        'today_appointments':today_appointments,
        'appointment_slots':appointment_slots,
        'recent_internal_messages':recent_internal_messages,
        'internal_unread':internal_unread,
        'chat_contacts':chat_contacts,
        'transfer_operators':transfer_operators,
        'routing_policy_notice':routing_policy_notice,
        'can_manage_groups':_can_manage_call_center_groups(request.user),
        'cockpit':cockpit,'work_queue':work_queue,'next_queue':next_queue,
        'queue_category_counts':category_counts,'upcoming_followups':upcoming_followups,
    })


@call_center_required
def call_center_today_appointments_live(request):
    """Read-only live journey for today's appointments owned by this call-center operator."""
    if request.method!='GET':
        return JsonResponse({'ok':False,'error':'method not allowed'},status=405)

    today=timezone.localdate()
    items=list(
        VisitAppointment.objects.filter(
            appointment_date=today,
            lead__assigned_to=request.user.profile,
        )
        .select_related('branch','lead','consultation_plan','consultation_plan__consultant')
        .order_by('appointment_time','id')[:20]
    )
    rows=[]
    for item in items:
        journey=_call_center_appointment_journey(item)
        rows.append({
            'id':item.pk,
            'name':item.full_name,
            'phone':item.phone,
            'branch':item.branch.name if item.branch_id else '—',
            'service':item.service or '',
            'time':item.appointment_time.strftime('%H:%M'),
            'status_key':journey['key'],
            'status_label':journey['label'],
            'status_source':journey['source'],
            'changed_time':journey['changed_time'],
            'needs_call':journey['needs_call'],
            'patient_url':reverse('patient_360_from_appointment',args=[item.pk]),
        })
    response=JsonResponse({
        'ok':True,
        'appointments':rows,
        'count':len(rows),
        'refreshed_at':timezone.localtime().strftime('%H:%M:%S'),
    },json_dumps_params={'ensure_ascii':False})
    response['Cache-Control']='no-store, private'
    return response


@call_center_required
def call_center_notebook(request):
    """Private, database-backed notebook for the signed-in call-center operator."""
    def serialize(entry):
        return {
            'id':entry.pk,
            'body':entry.body,
            'is_pinned':entry.is_pinned,
            'reminder_date':format_jalali(entry.reminder_date,persian_digits=False) if entry.reminder_date else '',
            'updated_at':timezone.localtime(entry.updated_at).strftime('%H:%M'),
        }

    if request.method=='GET':
        entries=PersonalNotebookEntry.objects.filter(user=request.user).order_by(
            '-is_pinned','-updated_at','-id'
        )[:80]
        response=JsonResponse({'ok':True,'entries':[serialize(item) for item in entries]})
        response['Cache-Control']='no-store, private'
        return response

    if request.method!='POST':
        return JsonResponse({'ok':False,'error':'method not allowed'},status=405)

    action=(request.POST.get('action') or 'save').strip()
    if action=='save':
        body=' '.join((request.POST.get('body') or '').strip().split())
        if not body:
            return JsonResponse({'ok':False,'error':'متن یادداشت خالی است.'},status=400)
        if len(body)>2000:
            return JsonResponse({'ok':False,'error':'یادداشت حداکثر ۲۰۰۰ کاراکتر می‌تواند باشد.'},status=400)

        raw_reminder=(request.POST.get('reminder_date') or '').strip()
        reminder_date=None
        if raw_reminder:
            try:
                reminder_date=parse_jalali(raw_reminder)
            except (TypeError,ValueError):
                return JsonResponse({'ok':False,'error':'تاریخ یادآوری شمسی معتبر نیست.'},status=400)

        pinned=(request.POST.get('is_pinned') or '').lower() in ('1','true','yes','on')
        entry_id=(request.POST.get('entry_id') or '').strip()
        if entry_id:
            if not entry_id.isdigit():
                return JsonResponse({'ok':False,'error':'یادداشت معتبر نیست.'},status=400)
            entry=get_object_or_404(PersonalNotebookEntry,pk=int(entry_id),user=request.user)
            entry.body=body
            entry.reminder_date=reminder_date
            entry.is_pinned=pinned
            entry.save(update_fields=['body','reminder_date','is_pinned','updated_at'])
        else:
            entry=PersonalNotebookEntry.objects.create(
                user=request.user,body=body,reminder_date=reminder_date,is_pinned=pinned
            )
        return JsonResponse({'ok':True,'entry':serialize(entry)})

    entry_id=(request.POST.get('entry_id') or '').strip()
    if not entry_id.isdigit():
        return JsonResponse({'ok':False,'error':'یادداشت معتبر نیست.'},status=400)
    entry=get_object_or_404(PersonalNotebookEntry,pk=int(entry_id),user=request.user)

    if action=='toggle_pin':
        entry.is_pinned=not entry.is_pinned
        entry.save(update_fields=['is_pinned','updated_at'])
        return JsonResponse({'ok':True,'entry':serialize(entry)})
    if action=='delete':
        entry.delete()
        return JsonResponse({'ok':True,'deleted':True})

    return JsonResponse({'ok':False,'error':'اقدام نامعتبر است.'},status=400)


@call_center_required
def call_center_lead_transfer(request,pk):
    """Manual temporary reassignment between active call-center flowers."""
    if request.method!='POST':
        return JsonResponse({'ok':False,'error':'method not allowed'},status=405)

    current=request.user.profile
    lead=get_object_or_404(
        ReferralLead.objects.select_related('assigned_to__user','group'),
        pk=pk,assigned_to=current,
    )
    if lead.status in ('won','lost'):
        return JsonResponse({'ok':False,'error':'لید بسته‌شده قابل انتقال نیست.'},status=400)

    target_id=(request.POST.get('target') or '').strip()
    if not target_id.isdigit():
        return JsonResponse({'ok':False,'error':'گل مقصد را انتخاب کنید.'},status=400)

    target=get_object_or_404(
        EmployeeProfile.objects.select_related('user'),
        pk=int(target_id),role='call_center',is_active=True,user__is_active=True,
    )
    if target.pk==current.pk:
        return JsonResponse({'ok':False,'error':'این لید همین حالا در صف شماست.'},status=400)

    old_group=lead.group
    target_group=old_group or _default_call_center_group(target)
    group_name=target_group.name

    old_name=call_center_display_name(current)
    target_name=call_center_display_name(target)
    now=timezone.now()

    with transaction.atomic():
        lead.assigned_to=target
        lead.assigned_at=now
        lead.group=target_group
        lead.save(update_fields=['assigned_to','assigned_at','group','updated_at'])

        AuditLog.objects.create(
            actor=request.user,
            action='lead_transfer',
            path=request.path,
            method='POST',
            object_type='ReferralLead',
            object_id=str(lead.pk),
            summary='انتقال موقت لید به گل دیگر',
            metadata={
                'lead_name':lead.full_name,
                'phone':lead.phone,
                'from_profile_id':current.pk,
                'from_flower':old_name,
                'to_profile_id':target.pk,
                'to_flower':target_name,
                'first_appointment_by_id':lead.first_appointment_by_id,
                'group':target_group.name,
            },
        )
        StaffNotification.objects.create(
            user=target.user,
            title='لید منتقل‌شده از گل دیگر',
            message=f'{lead.full_name} از {old_name} به صف شما منتقل شد.',
            notification_type='call_center_lead',
            related_date=timezone.localdate(),
        )

    return JsonResponse({
        'ok':True,
        'message':f'لید به {target_name} منتقل شد.',
        'target_name':target_name,
        'lead_id':lead.pk,
    },json_dumps_params={'ensure_ascii':False})


@call_center_required
def call_center_lead_name_update(request,pk):
    """Edit a lead name safely and keep linked appointment/patient displays in sync."""
    if request.method!='POST':
        return JsonResponse({'ok':False,'error':'method not allowed'},status=405)

    new_name=' '.join((request.POST.get('full_name') or '').strip().split())
    if len(new_name)<2:
        return JsonResponse({'ok':False,'error':'نام مراجع را کامل‌تر وارد کنید.'},status=400)
    if len(new_name)>140:
        return JsonResponse({'ok':False,'error':'نام مراجع حداکثر ۱۴۰ کاراکتر می‌تواند باشد.'},status=400)

    lead=get_object_or_404(
        ReferralLead.objects.select_related('assigned_to'),
        pk=pk,assigned_to=request.user.profile,
    )
    old_name=lead.full_name
    if new_name==old_name:
        return JsonResponse({'ok':True,'full_name':new_name,'unchanged':True})

    with transaction.atomic():
        lead.full_name=new_name
        lead.save(update_fields=['full_name','updated_at'])
        appointment_count=VisitAppointment.objects.filter(lead=lead).update(
            full_name=new_name,updated_at=timezone.now()
        )
        patient_count=PatientProfile.objects.filter(phone=lead.phone).update(
            full_name=new_name,updated_at=timezone.now()
        )
        AuditLog.objects.create(
            actor=request.user,
            action='lead_name_edit',
            path=request.path,
            method='POST',
            object_type='ReferralLead',
            object_id=str(lead.pk),
            summary='ویرایش نام مراجع در کال‌سنتر',
            metadata={
                'old_name':old_name,
                'new_name':new_name,
                'phone':lead.phone,
                'appointments_updated':appointment_count,
                'patient_profiles_updated':patient_count,
            },
        )

    return JsonResponse({
        'ok':True,'full_name':new_name,
        'appointments_updated':appointment_count,
        'patient_profiles_updated':patient_count,
    })


@call_center_required
def call_center_quick_message(request):
    if request.method!='POST':
        return JsonResponse({'ok':False,'error':'method not allowed'},status=405)
    body=(request.POST.get('body') or '').strip()
    target=(request.POST.get('recipient') or '').strip()
    if not body:
        return JsonResponse({'ok':False,'error':'متن پیام خالی است.'},status=400)
    if len(body)>1200:
        return JsonResponse({'ok':False,'error':'پیام حداکثر ۱۲۰۰ کاراکتر می‌تواند باشد.'},status=400)
    if not target.isdigit():
        return JsonResponse({'ok':False,'error':'گیرنده معتبر نیست.'},status=400)
    recipient=get_object_or_404(
        User.objects.select_related('profile','profile__branch'),
        pk=int(target),is_active=True,profile__is_active=True,
    )
    if recipient.pk==request.user.pk or recipient.profile.role=='referrer':
        return JsonResponse({'ok':False,'error':'گیرنده معتبر نیست.'},status=400)
    item=InternalMessage.objects.create(sender=request.user,recipient=recipient,body=body)
    StaffNotification.objects.create(
        user=recipient,
        title='پیام داخلی جدید',
        message=f'{request.user.get_full_name() or request.user.username}: {body[:140]}',
        notification_type='internal_message',
    )
    response=JsonResponse({
        'ok':True,
        'message':{
            'id':item.pk,
            'sender':request.user.get_full_name() or request.user.username,
            'recipient':recipient.get_full_name() or recipient.username,
            'body':item.body,
            'time':timezone.localtime(item.created_at).strftime('%H:%M'),
        },
    })
    response['Cache-Control']='no-store, private'
    return response


@login_required
def call_center_group_create(request):
    if not _can_manage_call_center_groups(request.user):
        messages.error(request,'ساخت گروه فقط برای مدیر یا سرگروه مجاز کال‌سنتر فعال است.')
        return redirect('dashboard')
    if request.method=='GET':
        groups=CallCenterLeadGroup.objects.annotate(lead_count=Count('leads')).order_by('-is_default','name','id')
        return render(request,'core/call_center/group_manage.html',{
            'groups':groups,
            'can_manage_groups':True,
        })
    if request.method!='POST':
        return redirect('call_center_group_create')
    name=' '.join((request.POST.get('name') or '').strip().split())
    if not name:
        messages.error(request,'نام گروه را وارد کنید.')
        return redirect('call_center_dashboard')
    if len(name)>80:
        messages.error(request,'نام گروه باید حداکثر ۸۰ کاراکتر باشد.')
        return redirect('call_center_dashboard')
    group,created=CallCenterLeadGroup.objects.get_or_create(
        name=name,defaults={'owner':None,'is_default':False},
    )
    if group.owner_id is not None:
        group.owner=None
        group.save(update_fields=['owner'])
    AuditLog.objects.create(
        actor=request.user,action='call_center_group_create',path=request.path,method='POST',
        object_type='CallCenterLeadGroup',object_id=str(group.pk),
        summary='Global call-center group created' if created else 'Existing global call-center group selected',
        metadata={'name':group.name,'created':created},
    )
    if created:
        messages.success(request,f'گروه سراسری «{group.name}» ساخته شد و برای همه گل‌ها قابل مشاهده است.')
    else:
        messages.info(request,f'گروه «{group.name}» از قبل وجود دارد.')
    if _role(request.user)=='call_center':
        return redirect(f"{reverse('call_center_dashboard')}?group={group.pk}")
    return redirect('call_center_group_create')


@call_center_required
def call_center_lead_create(request):
    if request.method!='POST':
        return redirect('call_center_dashboard')
    operator=request.user.profile
    _ensure_call_center_groups(operator)
    form=CallCenterLeadCreateForm(request.POST,operator=operator)
    if form.is_valid():
        lead=form.save(commit=False)
        lead.referrer=_call_center_direct_referrer()
        lead.assigned_to=None
        lead.group=None
        lead.created_by=request.user
        lead.source='panel'
        lead.save()
        assigned=_auto_assign_call_center(lead)
        if assigned:
            operator_name=assigned.user.get_full_name() or assigned.user.username
            messages.success(request,f'لید «{lead.full_name}» ثبت شد و طبق توزیع عادی به «{operator_name}» رسید.')
        else:
            messages.warning(request,'لید ثبت شد، اما فعلاً اپراتور واجد شرایطی برای توزیع پیدا نشد.')
        return redirect('call_center_dashboard')
    error=' '.join(message for messages_list in form.errors.values() for message in messages_list)
    messages.error(request,error or 'اطلاعات ثبت شماره کامل یا معتبر نیست.')
    group_id=(request.POST.get('group') or '').strip()
    if group_id.isdigit() and CallCenterLeadGroup.objects.filter(pk=group_id).exists():
        return redirect(f"{reverse('call_center_dashboard')}?group={group_id}")
    return redirect('call_center_dashboard')


@call_center_required
def call_center_direct_lead_create(request):
    operator=request.user.profile
    default_group=_default_call_center_group(operator)
    form=CallCenterDirectLeadForm(request.POST or None,default_group=default_group)
    if request.method=='POST' and form.is_valid():
        lead=form.save(commit=False)
        lead.referrer=_call_center_direct_referrer()
        lead.assigned_to=operator
        lead.assigned_at=timezone.now()
        lead.created_by=request.user
        lead.group=form.cleaned_data['group']
        lead.source='panel'
        direct_marker='[entry:direct]'
        lead.notes=f"{direct_marker}\n{lead.notes}".strip()
        try:
            lead.save()
        except DuplicateLeadError as exc:
            existing=getattr(exc,'existing_lead',None)
            if existing:
                owner=call_center_display_name(existing.assigned_to) if existing.assigned_to_id else 'بدون مسئول'
                messages.warning(
                    request,
                    f'این شماره اخیراً ثبت شده است: {existing.full_name} · مسئول: {owner}'
                )
            else:
                messages.warning(request,'این شماره اخیراً به‌عنوان لید ثبت شده است.')
        else:
            AuditLog.objects.create(
                actor=request.user,action='call_center_direct_lead_create',
                path=request.path,method='POST',
                object_type='ReferralLead',object_id=str(lead.pk),
                summary='Call-center operator registered lead directly into own queue',
                metadata={'group_id':lead.group_id,'group':lead.group.name,'phone':lead.phone},
            )
            messages.success(
                request,
                f'لید «{lead.full_name}» مستقیم در صف شما و گروه «{lead.group.name}» ثبت شد.'
            )
            return redirect(f"{reverse('call_center_dashboard')}?group={lead.group_id}")
    return render(request,'core/call_center/direct_lead_form.html',{
        'form':form,'can_manage_groups':_can_manage_call_center_groups(request.user),
    })


@call_center_required
def call_center_lead(request,pk):
    lead=get_object_or_404(
        ReferralLead.objects.select_related('assigned_to','group'),
        pk=pk,assigned_to=request.user.profile,
    )
    form=CallCenterLeadForm(request.POST or None,instance=lead,operator=request.user.profile)
    if request.method=='POST' and form.is_valid():
        # ModelForm validation mutates its in-memory instance; compare with DB.
        previous_result,previous_status=ReferralLead.objects.filter(pk=lead.pk).values_list(
            'contact_result','status'
        ).get()
        updated=form.save()
        from .sms_automation import queue_call_result_sms
        if (previous_result,previous_status)!=(updated.contact_result,updated.status):
            transaction.on_commit(lambda lead_id=updated.pk: queue_call_result_sms(lead_id))
        group_name=updated.group.name if updated.group_id else 'بدون گروه'
        messages.success(
            request,
            f'نتیجه تماس ذخیره شد؛ این لید اکنون در گروه «{group_name}» و در صف شما قرار دارد.'
        )
        return redirect('call_center_dashboard')
    real_appointments=lead.appointments.exclude(status='cancelled').select_related('branch').order_by('-appointment_date','-appointment_time')[:5]
    return render(request,'core/call_center/lead.html',{
        'lead':FlowerLeadProxy(lead),'form':form,'real_appointments':real_appointments,
    })


@login_required
def referral_sales(request):
    current=_ensure_profile(request.user)
    ids=_visible_profiles(request,current).values_list('id',flat=True)
    sales=ReferralSale.objects.filter(lead__referrer_id__in=ids).select_related(
        'lead','lead__referrer__user','lead__referrer__sponsor__user'
    )
    return render(request,'core/referrals/sales.html',{
        'referral':current,'sales':sales,'is_manager':_role(request.user) in ('admin','manager'),
        'sales_total':sales.filter(status__in=('approved','paid')).aggregate(x=Sum('amount'))['x'] or 0,
    })


@referral_manager_required
def referral_sale_edit(request,lead_pk):
    current=_ensure_profile(request.user)
    allowed_ids=_visible_profiles(request,current).values_list('id',flat=True)
    lead=get_object_or_404(ReferralLead.objects.select_related('referrer__user'),pk=lead_pk,referrer_id__in=allowed_ids)
    sale=ReferralSale.objects.filter(lead=lead).first()
    form=ReferralSaleForm(request.POST or None,instance=sale,initial={'sale_date':timezone.localdate()})
    if request.method=='POST' and form.is_valid():
        item=form.save(commit=False); item.lead=lead; item.recorded_by=request.user; item.save()
        if item.status!='cancelled' and lead.status!='won':
            lead.status='won'; lead.save(update_fields=['status','updated_at'])
        messages.success(request,'فروش و پورسانت ثبت شد.')
        return redirect('referral_sales')
    return render(request,'core/referrals/form.html',{
        'form':form,'title':'ثبت فروش و پورسانت','subtitle':f'{lead.full_name} · معرف: {lead.referrer}',
        'button':'ذخیره فروش','lead':lead,
    })


@referral_manager_required
def referral_export_csv(request):
    current=_ensure_profile(request.user)
    ids=_visible_profiles(request,current).values_list('id',flat=True)
    leads=ReferralLead.objects.filter(referrer_id__in=ids).select_related(
        'referrer__user','referrer__sponsor__user','assigned_to__user'
    ).order_by('-created_at')
    response=HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition']='attachment; filename="greenlife-referral-leads.csv"'
    response.write('\ufeff')
    writer=csv.writer(response)
    writer.writerow(['lead_id','نام مشتری','موبایل','خدمت','وضعیت','معرف','کد معرف','سطح','معرف بالادستی','مسئول پیگیری','تاریخ ثبت','crm_id','sync_status','مبلغ فروش','پورسانت مستقیم','پورسانت سطح دو'])
    for lead in leads:
        sale=getattr(lead,'sale',None)
        writer.writerow([
            lead.pk,lead.full_name,lead.phone,lead.interested_service,lead.get_status_display(),str(lead.referrer),
            lead.referrer.referral_code,lead.referrer.level,lead.referrer.sponsor or '',lead.assigned_to or '',
            timezone.localtime(lead.created_at).isoformat(),lead.crm_id or '',lead.sync_status,
            sale.amount if sale else '',sale.direct_commission if sale else '',sale.level_two_commission if sale else '',
        ])
    return response


@referral_manager_required
def referral_crm_export(request):
    current=_ensure_profile(request.user)
    profiles=_visible_profiles(request,current)
    ids=list(profiles.values_list('id',flat=True))
    leads=ReferralLead.objects.filter(referrer_id__in=ids).select_related('referrer','assigned_to__user')
    sales=ReferralSale.objects.filter(lead__referrer_id__in=ids).select_related('lead')
    payload={
        'schema':'greenlife.referrals.v1','generated_at':timezone.now().isoformat(),
        'referrers':[{
            'id':p.pk,'crm_id':p.crm_id,'sync_status':p.sync_status,'name':str(p),'phone':p.phone,
            'referral_code':p.referral_code,'sponsor_id':p.sponsor_id,'level':p.level,'active':p.is_active,
        } for p in profiles],
        'leads':[{
            'id':x.pk,'crm_id':x.crm_id,'sync_status':x.sync_status,'referrer_id':x.referrer_id,
            'full_name':x.full_name,'phone':x.phone,'alternate_phone':x.alternate_phone,
            'service':x.interested_service,'status':x.status,'source':x.source,
            'assigned_to_id':x.assigned_to_id,'next_follow_up':x.next_follow_up.isoformat() if x.next_follow_up else None,
            'notes':x.notes,'created_at':x.created_at.isoformat(),'updated_at':x.updated_at.isoformat(),
        } for x in leads],
        'sales':[{
            'id':x.pk,'crm_id':x.crm_id,'sync_status':x.sync_status,'lead_id':x.lead_id,
            'sale_date':x.sale_date.isoformat(),'amount':str(x.amount),'direct_commission':str(x.direct_commission),
            'level_two_commission':str(x.level_two_commission),'status':x.status,'updated_at':x.updated_at.isoformat(),
        } for x in sales],
    }
    return JsonResponse(payload,json_dumps_params={'ensure_ascii':False})
