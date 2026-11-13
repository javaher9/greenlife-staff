from datetime import date, timedelta
from django.db import transaction, IntegrityError
from django.http import HttpResponse, Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_GET
from .models import CustomerIntake, CustomerIntakePhoto, CustomerServiceRequest, CustomerPortalMember, EmployeeProfile, StaffNotification
from .customer_portal_views import _require_member, _member, _branches, _staff_gate, _visible_staff_requests
from .body_progress_views import _normalized_jpeg

def visit_intake(request):
    member=_require_member(request)
    if not isinstance(member,CustomerPortalMember): return member
    active=member.requests.filter(kind='visit',status__in=('pending','contacted')).first()
    error=''; data=request.POST if request.method=='POST' else {'full_name':member.full_name}
    if request.method=='POST' and not active:
        try:
            name=data.get('full_name','').strip()
            if not 3<=len(name)<=140: raise ValueError('نام و نام خانوادگی را کامل کنید.')
            branch=_branches().filter(pk=data.get('branch') or None).first()
            if not branch: raise ValueError('شعبه را انتخاب کنید.')
            daypart=data.get('daypart','any')
            if daypart not in ('any','morning','afternoon'): raise ValueError('بازه زمانی معتبر نیست.')
            preferred=date.fromisoformat(data['preferred_date']) if data.get('preferred_date') else None
            if preferred and not timezone.localdate()<=preferred<=timezone.localdate()+timedelta(days=90): raise ValueError('روز دلخواه باید در ۹۰ روز آینده باشد.')
            age=int(data['age']) if data.get('age') else None
            if age is not None and not 1<=age<=120: raise ValueError('سن را درست وارد کنید.')
            fields={k:data.get(k,'').strip() for k in ('city','address','goal','note')}
            if any(len(fields[k])>n for k,n in [('city',100),('address',400),('goal',300),('note',300)]): raise ValueError('یکی از توضیحات بیش از حد طولانی است.')
            uploads=request.FILES.getlist('photos')
            if len(uploads)>3: raise ValueError('حداکثر سه عکس انتخاب کنید.')
            if uploads and data.get('photo_consent')!='yes': raise ValueError('برای ذخیره خصوصی عکس‌ها رضایت خود را تأیید کنید.')
            images=[_normalized_jpeg(f) for f in uploads]
            if any(len(b)>2*1024*1024 for b in images): raise ValueError('عکس پس از آماده‌سازی بیش از حد بزرگ است؛ تصویر کوچک‌تری انتخاب کنید.')
            with transaction.atomic():
                row=CustomerServiceRequest.objects.create(member=member,kind='visit',branch=branch,preferred_date=preferred,daypart=daypart,note=fields.pop('note'))
                intake=CustomerIntake.objects.create(request=row,age=age,consent_at=timezone.now() if uploads else None,**fields)
                CustomerIntakePhoto.objects.bulk_create([CustomerIntakePhoto(intake=intake,content=b) for b in images])
                member.full_name=name; member.save(update_fields=['full_name'])
                staff=EmployeeProfile.objects.filter(is_active=True,user__is_active=True,role__in=('call_center','admin','internal_manager','manager')).select_related('user')
                StaffNotification.objects.bulk_create([StaffNotification(user=s.user,title='درخواست جدید ویزیت',message=f'{name} | {branch.name} | شماره درخواست {row.pk}',notification_type='info') for s in staff if s.role!='manager' or s.branch_id==branch.pk])
            return redirect('customer_request',kind='visit')
        except (ValueError,TypeError):
            error='اطلاعات یا عکس معتبر نیست. نام، شعبه، سن، تاریخ و رضایت عکس را بررسی کنید. حداکثر ۳ عکس JPG، PNG یا WebP، هرکدام تا ۸ مگابایت و حداقل ۲۰۰ پیکسل پذیرفته می‌شود.'
        except IntegrityError:
            return redirect('customer_request',kind='visit')
    rows=member.requests.filter(kind='visit').select_related('intake','branch').prefetch_related('intake__photos')[:8]
    response=render(request,'core/customer_portal/intake.html',{'member':member,'active':active,'rows':rows,'data':data,'error':error,'branches':_branches(),'today':timezone.localdate().isoformat()})
    response['Cache-Control']='private, no-store';return response

@require_GET
def intake_photo(request,public_id):
    photo=get_object_or_404(CustomerIntakePhoto.objects.select_related('intake__request'),public_id=public_id)
    member=_member(request)
    if not member or member.pk!=photo.intake.request.member_id:
        if not request.user.is_authenticated: raise Http404()
        _staff_gate(request)
        if not _visible_staff_requests(request).filter(pk=photo.intake.request_id).exists(): raise Http404()
    response=HttpResponse(bytes(photo.content),content_type='image/jpeg')
    response['Cache-Control']='private, no-store'
    response['X-Content-Type-Options']='nosniff'
    response['Content-Disposition']='inline; filename="intake.jpg"'
    return response
