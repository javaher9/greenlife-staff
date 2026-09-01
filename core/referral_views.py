import csv
import io
import os
import uuid
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Q, Sum
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import (
    PublicReferralLeadForm, ReferralLeadForm, ReferralLeadManageForm,
    ReferralMemberForm, ReferralSaleForm,
)
from .models import EmployeeProfile, ReferralLead, ReferralProfile, ReferralSale


def _role(user):
    return getattr(getattr(user, 'profile', None), 'role', 'employee')


def referral_manager_required(view):
    @wraps(view)
    @login_required
    def wrapper(request, *args, **kwargs):
        if _role(request.user) not in ('admin', 'manager'):
            messages.error(request, 'این بخش فقط برای مدیریت قابل دسترسی است.')
            return redirect('referral_dashboard')
        return view(request, *args, **kwargs)
    return wrapper


def _new_code():
    while True:
        code=f'GL{uuid.uuid4().hex[:8].upper()}'
        if not ReferralProfile.objects.filter(referral_code=code).exists():
            return code


def _ensure_profile(user):
    if _role(user)=='internal_manager':
        raise PermissionDenied('دسترسی شبکه فروش برای نقش مدیر داخلی فعال نیست.')
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


@login_required
def referral_dashboard(request):
    current=_ensure_profile(request.user)
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
        'can_add_member':current.level<2,'is_manager':_role(request.user) in ('admin','manager'),
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
    return render(request, 'core/referrals/dashboard.html', context)


@login_required
def referral_guide(request):
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
            ReferralProfile.objects.create(
                user=user,sponsor=sponsor,referral_code=_new_code(),phone=d['phone'],
                photo=d.get('photo'),created_by=request.user,
            )
        messages.success(request,'عضو جدید شبکه ساخته شد و اکنون می‌تواند وارد پنل شود.')
        return redirect('referral_network')
    return render(request,'core/referrals/form.html',{
        'form':form,'title':'افزودن عضو شبکه','subtitle':f'زیرمجموعه {sponsor}',
        'button':'ساخت حساب معرف','sponsor':sponsor,
    })


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
        messages.success(request,'لید ثبت شد و در صف پیگیری قرار گرفت.')
        return redirect('referral_lead_list')
    return render(request,'core/referrals/form.html',{
        'form':form,'title':'ثبت لید جدید','subtitle':f'معرف: {referrer}',
        'button':'ثبت مشتری','referrer':referrer,
    })


def public_referral_lead(request,code):
    referrer=get_object_or_404(ReferralProfile.objects.select_related('user'),referral_code=code,is_active=True)
    form=PublicReferralLeadForm(request.POST or None)
    completed=False
    if request.method=='POST' and form.is_valid():
        lead=form.save(commit=False); lead.referrer=referrer
        lead.source='qr' if request.GET.get('src')=='qr' else 'link'
        lead.source_url=request.build_absolute_uri()[:500]
        lead.save(); completed=True; form=PublicReferralLeadForm()
    return render(request,'core/referrals/public_lead.html',{
        'form':form,'referrer':referrer,'completed':completed,'photo':_photo_url(referrer),
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
        form.save(); messages.success(request,'وضعیت پیگیری لید به‌روزرسانی شد.')
        return redirect('referral_lead_list')
    return render(request,'core/referrals/form.html',{
        'form':form,'title':f'پیگیری {lead.full_name}','subtitle':f'{lead.phone} · معرف: {lead.referrer}',
        'button':'ذخیره پیگیری','lead':lead,
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
