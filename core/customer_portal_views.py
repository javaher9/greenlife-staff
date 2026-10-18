"""Mobile-first verified customer portal; separate from internal staff appointment views."""
import secrets
from datetime import date, timedelta
from urllib.parse import quote

from django.contrib.auth.hashers import check_password, make_password
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.db.models import Sum, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from .models import (
    Branch, CustomerPortalMember, CustomerPortalOTP, CustomerServiceRequest,
    CustomerClubReferral, CustomerClubPoints, CustomerClubPolicy, StaffNotification,
    EmployeeProfile, VisitAppointment, DeviceSessionBooking, normalize_lead_phone,
    SmsMessageLog,
)
from .sms import send_sms, SmsGatewayError

OTP_LIFETIME=timedelta(minutes=5)
MEMBER_LIFETIME=timedelta(days=7)
STAFF_ADMIN=('admin','internal_manager','manager')
STAFF_VISIT=('call_center','admin','internal_manager','manager')
STAFF_DEVICE=('consultant','admin','internal_manager','manager')
STAFF_NETWORK=('admin','internal_manager')


def _role(request):
    if request.user.is_superuser:
        return 'admin'
    return getattr(getattr(request.user,'profile',None),'role','none')


def _is_staff_allowed(request,kind):
    role=_role(request)
    return role in {
        'visit':STAFF_VISIT,'device':STAFF_DEVICE,'network':STAFF_NETWORK,
    }.get(kind,())


def _branches():
    return Branch.objects.filter(is_active=True).exclude(
        Q(name__icontains='افسریه')|Q(name__icontains='ارومیه')
        |Q(name__icontains='کال‌سنتر')|Q(name__icontains='کال سنتر')
        |Q(name__icontains='call center')
    ).order_by('name')


def _member(request):
    member_id=request.session.get('gl_customer_member_id')
    at=request.session.get('gl_customer_auth_at')
    if not member_id or not at:
        return None
    try:
        if timezone.now().timestamp()-float(at)>MEMBER_LIFETIME.total_seconds():
            return None
    except (ValueError,TypeError):
        return None
    return CustomerPortalMember.objects.filter(pk=member_id).first()


def _require_member(request):
    member=_member(request)
    if member:
        return member
    path=request.get_full_path()
    return redirect(reverse('customer_login')+'?next='+quote(path,safe=''))


def _new_member(phone):
    existing=CustomerPortalMember.objects.filter(phone=phone).first()
    if existing:
        return existing
    for _ in range(5):
        try:
            return CustomerPortalMember.objects.create(
                phone=phone,referral_code='GLC'+secrets.token_hex(6).upper()
            )
        except IntegrityError:
            existing=CustomerPortalMember.objects.filter(phone=phone).first()
            if existing:return existing
    raise RuntimeError('Unable to create customer identifier')


def _pending_invitation(request, member):
    code=request.session.pop('gl_pending_invite',None)
    if not code:
        return
    inviter=CustomerPortalMember.objects.filter(referral_code=code).first()
    if inviter and inviter.id!=member.id:
        CustomerClubReferral.objects.get_or_create(
            invited=member,defaults={'referrer':inviter},
        )


@require_http_methods(['GET','POST'])
def customer_login(request):
    """Fail-closed SMS OTP. Unverified phone never grants customer access."""
    current=_member(request)
    if current:
        return redirect('customer_club')
    error=''
    saved_next=request.session.get('gl_customer_next') or reverse('customer_club')
    if request.method=='GET':
        candidate=request.GET.get('next','')
        if candidate.startswith('/customer/') and url_has_allowed_host_and_scheme(
            candidate,allowed_hosts={request.get_host()},require_https=request.is_secure()
        ):
            request.session['gl_customer_next']=candidate
    step='verify' if request.session.get('gl_pending_phone') else 'send'
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='send':
            phone=normalize_lead_phone(request.POST.get('phone',''))
            if not (len(phone)==11 and phone.startswith('09') and phone.isdigit()):
                error='شماره موبایل معتبر وارد کنید.'
            else:
                # Best-effort IP throttle plus persistent phone throttle.
                ip=request.META.get('REMOTE_ADDR','')[:48]
                throttle_key='cust-otp-ip:'+ip
                if not cache.add(throttle_key,'1',timeout=15):
                    error='کمی صبر کنید و دوباره تلاش کنید.'
                else:
                    now=timezone.now()
                    with transaction.atomic():
                        otp,_=CustomerPortalOTP.objects.select_for_update().get_or_create(phone=phone)
                        if otp.sent_at and now-otp.sent_at<timedelta(seconds=90):
                            error='کد اخیراً ارسال شده است. لطفاً کمی صبر کنید.'
                        else:
                            if not otp.window_started_at or now-otp.window_started_at>=timedelta(hours=1):
                                otp.window_started_at=now
                                otp.sends_in_window=0
                            if otp.sends_in_window>=4:
                                error='سقف درخواست کد این ساعت تکمیل شده است.'
                            else:
                                code=f'{secrets.randbelow(1000000):06d}'
                                otp.code_hash=make_password(code)
                                otp.expires_at=now+OTP_LIFETIME
                                otp.sent_at=now
                                otp.sends_in_window+=1
                                otp.failed_attempts=0
                                otp.save()
                                try:
                                    log,_=send_sms(phone,f'کد ورود گرین‌لایف: {code}\nاعتبار: ۵ دقیقه',purpose='manual')
                                except SmsGatewayError:
                                    otp.code_hash=''
                                    otp.expires_at=None
                                    otp.save(update_fields=['code_hash','expires_at'])
                                    # Never retain raw OTP in failed gateway logs.
                                    SmsMessageLog.objects.filter(number=phone,body__contains=code).update(
                                        body='کد یک‌بارمصرف گرین‌لایف [حذف شد]',
                                    )
                                    error='ارسال پیامک در دسترس نیست؛ کمی بعد تلاش کنید.'
                                else:
                                    # Mask OTP even in staff-visible SMS logs.
                                    SmsMessageLog.objects.filter(pk=log.pk).update(
                                        body='کد یک‌بارمصرف گرین‌لایف [حذف شد]',
                                    )
                                    request.session['gl_pending_phone']=phone
                                    step='verify'
        elif action=='verify':
            phone=request.session.get('gl_pending_phone')
            code=''.join(ch for ch in request.POST.get('code','').translate(
                str.maketrans('۰۱۲۳۴۵۶۷۸۹','0123456789')) if ch.isdigit())
            if not phone or len(code)!=6:
                error='کد شش‌رقمی وارد کنید.'
            else:
                with transaction.atomic():
                    otp=CustomerPortalOTP.objects.select_for_update().filter(phone=phone).first()
                    now=timezone.now()
                    if not otp or not otp.code_hash or not otp.expires_at or now>otp.expires_at:
                        error='اعتبار کد تمام شده است؛ کد جدید دریافت کنید.'
                    elif otp.failed_attempts>=5:
                        error='تعداد تلاش مجاز تمام شده است؛ کد جدید دریافت کنید.'
                    elif not check_password(code,otp.code_hash):
                        otp.failed_attempts+=1
                        otp.save(update_fields=['failed_attempts'])
                        error='کد واردشده صحیح نیست.'
                    else:
                        otp.code_hash=''
                        otp.expires_at=None
                        otp.save(update_fields=['code_hash','expires_at'])
                        member=_new_member(phone)
                        member.last_login_at=now
                        member.save(update_fields=['last_login_at'])
                        request.session.cycle_key()
                        request.session['gl_customer_member_id']=member.pk
                        request.session['gl_customer_auth_at']=now.timestamp()
                        request.session.pop('gl_pending_phone',None)
                        _pending_invitation(request,member)
                        target=request.session.pop('gl_customer_next',None)
                        if not target or not target.startswith('/customer/'):
                            target=reverse('customer_club')
                        return redirect(target)
        elif action=='restart':
            request.session.pop('gl_pending_phone',None)
            step='send'
        else:
            error='درخواست نامعتبر است.'
    response=render(request,'core/customer_portal/login.html',{'error':error,'step':step})
    response['Cache-Control']='private, no-store'
    return response


@require_POST
def customer_logout(request):
    for key in ('gl_customer_member_id','gl_customer_auth_at','gl_pending_phone'):
        request.session.pop(key,None)
    return redirect('customer_login')


@require_http_methods(['GET','POST'])
def customer_request(request,kind):
    if kind not in ('visit','device','network'):
        raise Http404()
    member=_require_member(request)
    if not isinstance(member,CustomerPortalMember):
        return member
    error=''
    active=member.requests.filter(kind=kind,status__in=('pending','contacted')).select_related('branch').first()
    if request.method=='POST' and not active:
        branches=_branches()
        try:
            branch=branches.get(pk=int(request.POST.get('branch','0')))
        except (ValueError,TypeError,Branch.DoesNotExist):
            branch=None
        full_name=(request.POST.get('full_name') or member.full_name).strip()[:140]
        daypart=request.POST.get('daypart','any')
        note=request.POST.get('note','').strip()[:300]
        raw_date=request.POST.get('preferred_date','').strip()
        preferred_date=None
        if raw_date:
            try: preferred_date=date.fromisoformat(raw_date)
            except ValueError: error='تاریخ انتخاب‌شده معتبر نیست.'
        if not error and preferred_date and not timezone.localdate()<=preferred_date<=timezone.localdate()+timedelta(days=90):
            error='تاریخ را در ۹۰ روز آینده انتخاب کنید.'
        if not branch or len(full_name)<3 or daypart not in ('any','morning','afternoon'):
            error='نام، شعبه و زمان ترجیحی را کامل کنید.'
        if not error:
            try:
                with transaction.atomic():
                    member.full_name=full_name
                    member.save(update_fields=['full_name'])
                    active=CustomerServiceRequest.objects.create(
                        member=member,kind=kind,branch=branch,
                        preferred_date=preferred_date,daypart=daypart,note=note,
                    )
            except IntegrityError:
                active=member.requests.filter(kind=kind,status__in=('pending','contacted')).first()
                if not active:
                    error='درخواست ثبت نشد؛ دوباره امتحان کنید.'
            if active:
                notify_kind=('ویزیت' if kind=='visit' else 'دستگاه' if kind=='device' else 'شبکه فروش')
                targets=EmployeeProfile.objects.filter(
                    is_active=True,user__is_active=True,role__in={
                        'visit':['call_center','admin','internal_manager','manager'],
                        'device':['consultant','admin','internal_manager','manager'],
                        'network':['admin','internal_manager'],
                    }[kind]
                ).select_related('user')
                rows=[]
                for staff in targets:
                    if staff.role in ('consultant','manager') and staff.branch_id!=branch.id:
                        continue
                    rows.append(StaffNotification(
                        user=staff.user,title=f'درخواست جدید {notify_kind}',
                        message=f'{full_name} | {branch.name} | {member.phone} | شماره درخواست {active.pk}',
                        notification_type='info',
                    ))
                StaffNotification.objects.bulk_create(rows)
                return redirect('customer_request',kind=kind)
    requests=list(member.requests.filter(kind=kind).select_related('branch').order_by('-created_at')[:8])
    response=render(request,'core/customer_portal/request.html',{
        'kind':kind,'member':member,'active':active,'requests':requests,
        'branches':_branches(),'error':error,
        'today':timezone.localdate().isoformat(),
        'title':dict(CustomerServiceRequest.KINDS)[kind],
    })
    response['Cache-Control']='private, no-store'
    return response


def customer_join(request,code):
    inviter=CustomerPortalMember.objects.filter(referral_code=code).first()
    if not inviter:
        raise Http404()
    request.session['gl_pending_invite']=code
    member=_member(request)
    if member:
        _pending_invitation(request,member)
        return redirect('customer_club')
    return redirect(reverse('customer_login')+'?next='+quote(reverse('customer_club')))


@require_http_methods(['GET'])
def customer_club(request):
    member=_require_member(request)
    if not isinstance(member,CustomerPortalMember):
        return member
    balance=member.points_entries.aggregate(total=Sum('amount'))['total'] or 0
    referrals=member.invited_members.select_related('invited').all()
    my_requests=member.requests.exclude(kind='network').select_related('branch')[:5]
    policy=CustomerClubPolicy.objects.filter(pk=1).first()
    response=render(request,'core/customer_portal/club.html',{
        'member':member,'balance':balance,'referrals':referrals,
        'referrals_count':referrals.count(),
        'qualified_count':referrals.filter(status='qualified').count(),
        'invite_url':request.build_absolute_uri(reverse('customer_join',args=[member.referral_code])),
        'policy':policy,'my_requests':my_requests,
    })
    response['Cache-Control']='private, no-store'
    return response


def _staff_gate(request):
    if not request.user.is_authenticated or _role(request) not in (
        'admin','internal_manager','manager','call_center','consultant'
    ):
        raise PermissionDenied('دسترسی به درخواست‌های مشتریان برای این نقش فعال نیست.')


def _visible_staff_requests(request):
    role=_role(request)
    qs=CustomerServiceRequest.objects.select_related(
        'member','branch','assigned_to','visit_appointment','device_session'
    )
    if role in ('admin','internal_manager'):
        return qs
    profile=getattr(request.user,'profile',None)
    if role=='call_center':
        return qs.filter(kind='visit')
    if role=='consultant':
        return qs.filter(kind='device',branch_id=profile.branch_id) if profile and profile.branch_id else qs.none()
    if role=='manager':
        return qs.filter(branch_id=profile.branch_id) if profile and profile.branch_id else qs.none()
    return qs.none()


@require_http_methods(['GET'])
def staff_customer_requests(request):
    _staff_gate(request)
    qs=_visible_staff_requests(request)
    selected=request.GET.get('status','pending')
    if selected not in ('pending','contacted','booked','declined','all'):
        selected='pending'
    if selected!='all':
        qs=qs.filter(status=selected)
    return render(request,'core/customer_portal/staff_requests.html',{
        'rows':qs[:120],'selected':selected,'role':_role(request)
    })


@require_POST
def staff_customer_request_action(request,pk):
    _staff_gate(request)
    with transaction.atomic():
        row=get_object_or_404(_visible_staff_requests(request).select_for_update(),pk=pk)
        if not _is_staff_allowed(request,row.kind):
            raise PermissionDenied()
        action=request.POST.get('action')
        role=_role(request)
        if row.assigned_to_id and role not in ('admin','internal_manager') and row.assigned_to_id!=getattr(getattr(request.user,'profile',None),'pk',None):
            raise PermissionDenied('این درخواست توسط همکار دیگری در حال پیگیری است.')
        if action=='claim' and row.status=='pending':
            row.status='contacted'
            row.assigned_to=getattr(request.user,'profile',None)
        elif action=='decline' and row.status in ('pending','contacted'):
            note=request.POST.get('staff_note','').strip()
            if not note:
                raise PermissionDenied('برای بستن درخواست باید علت ثبت شود.')
            row.staff_note=note[:300]
            row.status='declined'
            row.resolved_by=request.user
        elif action=='book' and row.status in ('pending','contacted') and row.kind!='network':
            id_text=request.POST.get('booking_id','').strip()
            if not id_text.isdigit():
                raise PermissionDenied('برای تأیید، شماره نوبت واقعی ثبت‌شده در CRM را وارد کنید.')
            if row.kind=='visit':
                booking=get_object_or_404(
                    VisitAppointment,pk=int(id_text),branch_id=row.branch_id,
                    status__in=('booked','arrived','completed')
                )
                if normalize_lead_phone(booking.phone)!=row.member.phone:
                    raise PermissionDenied('شماره تماس نوبت با درخواست مشتری مطابقت ندارد.')
                row.visit_appointment=booking
            else:
                booking=get_object_or_404(
                    DeviceSessionBooking.objects.select_related('appointment'),pk=int(id_text),
                    branch_id=row.branch_id,status__in=('booked','arrived','completed')
                )
                if normalize_lead_phone(booking.appointment.phone)!=row.member.phone:
                    raise PermissionDenied('شماره تماس جلسه با درخواست مشتری مطابقت ندارد.')
                row.device_session=booking
            row.status='booked'
            row.assigned_to=getattr(request.user,'profile',None)
            row.resolved_by=request.user
        elif action=='network_review' and row.kind=='network' and row.status in ('pending','contacted'):
            row.status='contacted'
            row.assigned_to=getattr(request.user,'profile',None)
            row.staff_note='درخواست عضویت برای بررسی مدیریت دریافت شد.'
        else:
            raise PermissionDenied('تغییر وضعیت درخواست مجاز نیست.')
        row.save()
    return redirect(reverse('staff_customer_requests')+'?status=all')


def _club_admin(request):
    if not request.user.is_authenticated or _role(request) not in ('admin','internal_manager'):
        raise PermissionDenied('مدیریت امتیاز فقط برای مدیر مجاز است.')


@require_http_methods(['GET','POST'])
def staff_customer_club(request):
    _club_admin(request)
    error=''
    policy,_=CustomerClubPolicy.objects.get_or_create(pk=1)
    if request.method=='POST':
        action=request.POST.get('action')
        if action=='policy':
            amount_text=request.POST.get('referral_points','')
            if not amount_text.isdigit() or int(amount_text)>100000:
                error='امتیاز باید بین صفر تا ۱۰۰٬۰۰۰ باشد.'
            else:
                policy.referral_points=int(amount_text)
                policy.enabled=request.POST.get('enabled')=='on'
                policy.updated_by=request.user
                policy.save()
                return redirect('staff_customer_club')
        elif action in ('qualify','award'):
            rid=request.POST.get('referral_id','')
            if not rid.isdigit():
                error='شناسه معرفی معتبر نیست.'
            else:
                with transaction.atomic():
                    ref=CustomerClubReferral.objects.select_for_update().select_related(
                        'invited','referrer').filter(pk=int(rid)).first()
                    if not ref:
                        error='معرفی یافت نشد.'
                    else:
                        valid_visit=VisitAppointment.objects.filter(
                            phone=ref.invited.phone,status__in=('arrived','completed')
                        ).exists()
                        if not valid_visit:
                            error='مراجعه تأییدشده‌ای برای شماره دوست ثبت نشده است.'
                        else:
                            if ref.status!='qualified':
                                ref.status='qualified'
                                ref.qualified_at=timezone.now()
                                ref.qualified_by=request.user
                                ref.save()
                            policy=CustomerClubPolicy.objects.filter(pk=1).first()
                            if policy and policy.enabled and policy.referral_points>0:
                                CustomerClubPoints.objects.get_or_create(
                                    referral=ref,
                                    defaults={
                                        'member':ref.referrer,
                                        'amount':policy.referral_points,
                                        'approved_by':request.user,
                                    },
                                )
                            return redirect('staff_customer_club')
        else:
            error='درخواست نامعتبر است.'
    return render(request,'core/customer_portal/staff_club.html',{
        'policy':policy,'error':error,
        'referrals':CustomerClubReferral.objects.select_related('referrer','invited')[:100],
    })
