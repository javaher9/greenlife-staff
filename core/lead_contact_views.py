import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .lead_contacts import clean_numbers, conflicting_lead, contact_payload, contacts_version, lock_numbers, store_additional
from .models import AuditLog, PatientProfile, ReferralLead, VisitAppointment, lead_phone_variants


@login_required
@require_http_methods(['GET','POST'])
@transaction.atomic
def lead_contacts(request, pk):
    profile=getattr(request.user,'profile',None)
    if not profile or profile.role!='call_center' or not profile.is_active:
        return JsonResponse({'ok':False,'error':'دسترسی مجاز نیست.'},status=403)
    queryset=ReferralLead.objects.filter(assigned_to=profile)
    if request.method=='POST':
        queryset=queryset.select_for_update()
    lead=get_object_or_404(queryset,pk=pk)
    if request.method=='GET':
        history=[]
        for log in AuditLog.objects.filter(action='lead_phone_edit',object_type='ReferralLead',object_id=str(lead.pk)).select_related('actor').order_by('-id')[:10]:
            history.append({'actor':log.actor.get_full_name() or log.actor.username if log.actor else '—',
                            'at':timezone.localtime(log.created_at).strftime('%Y-%m-%d %H:%M'),
                            'before':log.metadata.get('before',[]),'after':log.metadata.get('after',[])})
        return JsonResponse({'ok':True,**contact_payload(lead),'history':history})
    try:
        data=json.loads(request.body)
        if not isinstance(data,dict):
            raise ValueError()
        numbers=clean_numbers(data.get('phone'),data.get('additional',[]))
    except (ValueError,TypeError,UnicodeDecodeError,ValidationError) as exc:
        message=' '.join(exc.messages) if isinstance(exc,ValidationError) else 'اطلاعات شماره‌ها معتبر نیست.'
        return JsonResponse({'ok':False,'error':message},status=400)
    if data.get('version')!=contacts_version(lead):
        return JsonResponse({'ok':False,'error':'شماره‌ها در صفحهٔ دیگری تغییر کرده‌اند. پنجره را دوباره باز کنید.'},status=409)
    before=lead.contact_numbers
    if numbers==before:
        return JsonResponse({'ok':True,**contact_payload(lead),'unchanged':True})
    lock_numbers(before+numbers)
    for number in set(numbers)-set(before):
        if conflicting_lead(number,lead.pk):
            return JsonResponse({'ok':False,'error':'شمارهٔ '+number+' قبلاً در لید دیگری ثبت شده است؛ تغییری ذخیره نشد.'},status=409)
    old_primary=lead.phone
    patient=None
    old_variants=lead_phone_variants(old_primary)
    if numbers[0]!=old_primary:
        patients=list(PatientProfile.objects.select_for_update().filter(phone__in=old_variants))
        target=PatientProfile.objects.filter(phone__in=lead_phone_variants(numbers[0]))
        if patients:
            patient=patients[0]
            if (len(patients)>1 or patient.full_name.strip()!=lead.full_name.strip()
                or ReferralLead.objects.filter(phone__in=old_variants).exclude(pk=lead.pk).exists()
                or VisitAppointment.objects.filter(phone__in=old_variants).exclude(lead=lead).exists()):
                return JsonResponse({'ok':False,'error':'این شماره به سوابق مشترک چند پرونده متصل است؛ اصلاح شمارهٔ اصلی نیاز به بررسی مدیر دارد. شمارهٔ دیگر را می‌توانید اضافه کنید.'},status=409)
            target=target.exclude(pk=patient.pk)
        if target.exists():
            return JsonResponse({'ok':False,'error':'شمارهٔ اصلی جدید در پروندهٔ بیمار دیگری وجود دارد؛ ادغام خودکار انجام نمی‌شود.'},status=409)
    lead.phone=numbers[0]
    lead.alternate_phone=numbers[1] if len(numbers)>1 else ''
    lead.save(update_fields=['phone','alternate_phone','updated_at'])
    store_additional(lead,numbers[1:])
    appointments=0
    if numbers[0]!=old_primary:
        appointments=VisitAppointment.objects.filter(lead=lead,phone__in=old_variants).update(phone=numbers[0],updated_at=timezone.now())
        if patient:
            PatientProfile.objects.filter(pk=patient.pk).update(phone=numbers[0],updated_at=timezone.now())
    AuditLog.objects.create(actor=request.user,action='lead_phone_edit',path=request.path,method='POST',
                            object_type='ReferralLead',object_id=str(lead.pk),summary='ویرایش شماره‌های مراجع در کال‌سنتر',
                            metadata={'before':before,'after':numbers,'old_primary':old_primary,'new_primary':numbers[0],
                                      'appointments_updated':appointments,'patient_id':patient.pk if patient else None})
    return JsonResponse({'ok':True,**contact_payload(lead)})
