from datetime import datetime, time
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Avg, Min, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import (
    BodyAnalysisRecord, DeviceSessionBooking, FinancialTransaction, PatientCareNote,
    PatientDeviceProgram, PatientDietProgram, PatientLipolyticProgram, PatientProfile,
    PatientTeamRating, ReferralLead, SmsMessageLog, VisitAppointment, lead_phone_variants,
    normalize_lead_phone,
)
from .sms import SmsGatewayError, send_sms


ALLOWED_ROLES={'admin','internal_manager','manager','doctor','consultant','receptionist','call_center'}


def _profile(request):
    profile=getattr(request.user,'profile',None)
    if not profile or profile.role not in ALLOWED_ROLES:
        raise PermissionDenied('دسترسی به پرونده ۳۶۰ بیمار برای این نقش فعال نیست.')
    return profile


def _can_view_full_phone(request, profile):
    return bool(request.user.is_superuser or profile.role in {'admin','internal_manager'})


def _assert_patient_access(request, patient, profile):
    variants=lead_phone_variants(patient.phone)
    if profile.role=='call_center':
        allowed=ReferralLead.objects.filter(phone__in=variants).filter(
            Q(assigned_to=profile) | Q(first_appointment_by=request.user) | Q(created_by=request.user)
        ).exists()
        if not allowed:
            raise PermissionDenied('این پرونده در چرخه کاری شما قرار ندارد.')
        return
    if profile.role in {'manager','doctor','consultant','receptionist'} and profile.branch_id:
        if patient.home_branch_id and patient.home_branch_id!=profile.branch_id:
            if not VisitAppointment.objects.filter(
                branch_id=profile.branch_id,phone__in=variants,
            ).exists():
                raise PermissionDenied('این پرونده برای شعبه شما قابل مشاهده نیست.')


def _masked_phone(value):
    digits=''.join(ch for ch in str(value or '') if ch.isdigit())
    if not digits:
        return '—'
    if len(digits)<=7:
        return '***'
    return f'{digits[:4]}***{digits[-4:]}'


def _age(birth_date):
    if not birth_date:
        return None
    today=timezone.localdate()
    return today.year-birth_date.year-((today.month,today.day)<(birth_date.month,birth_date.day))


def _phone_matched_profiles(phone):
    variants=lead_phone_variants(phone)
    return list(PatientProfile.objects.filter(phone__in=variants).select_related('home_branch').order_by('id'))


def _hydrate_from_siblings(patient, siblings):
    """Fill only blank stable demographics from same-mobile records; never overwrite."""
    fields=('birth_date','sex','height_cm','neighborhood','address_summary','medical_history','crm_id')
    changed=[]
    for field in fields:
        if getattr(patient,field):
            continue
        value=next((getattr(item,field) for item in siblings if getattr(item,field)),None)
        if value:
            setattr(patient,field,value)
            changed.append(field)
    if not patient.is_vip and any(item.is_vip for item in siblings):
        patient.is_vip=True
        changed.append('is_vip')
    if changed:
        changed.append('updated_at')
        patient.save(update_fields=changed)


def _patient_from_appointment(appointment, user):
    phone=normalize_lead_phone(appointment.phone)
    if not phone:
        return None
    matches=_phone_matched_profiles(phone)
    patient=next((item for item in matches if normalize_lead_phone(item.phone)==phone),None)
    if not patient:
        patient=PatientProfile.objects.create(
            phone=phone,
            full_name=appointment.full_name,
            home_branch=appointment.branch,
            created_by=user,
        )
        matches=[patient]
    changed=[]
    if appointment.full_name and patient.full_name!=appointment.full_name:
        patient.full_name=appointment.full_name
        changed.append('full_name')
    if not patient.home_branch_id and appointment.branch_id:
        patient.home_branch=appointment.branch
        changed.append('home_branch')
    if patient.phone!=phone and not PatientProfile.objects.filter(phone=phone).exclude(pk=patient.pk).exists():
        patient.phone=phone
        changed.append('phone')
    if changed:
        changed.append('updated_at')
        patient.save(update_fields=changed)
    _hydrate_from_siblings(patient,matches)
    return patient


def _join_text(parts):
    clean=[]
    for value in parts:
        value=(value or '').strip()
        if value and value not in clean:
            clean.append(value)
    return ' • '.join(clean)


@login_required
def patient_360_from_appointment(request, appointment_id):
    profile=_profile(request)
    appointment=get_object_or_404(
        VisitAppointment.objects.select_related('branch'),
        pk=appointment_id,
    )
    if profile.role in {'manager','doctor','consultant','receptionist'} and profile.branch_id:
        if appointment.branch_id!=profile.branch_id:
            raise PermissionDenied('این بیمار متعلق به شعبه شما نیست.')
    patient=_patient_from_appointment(appointment,request.user)
    if not patient:
        messages.error(request,'شماره موبایل معتبر برای ساخت پرونده بیمار وجود ندارد.')
        return redirect('dashboard')
    return redirect('patient_360',pk=patient.pk)


@login_required
def patient_360(request, pk):
    profile=_profile(request)
    patient=get_object_or_404(
        PatientProfile.objects.select_related('home_branch','created_by'),
        pk=pk,
    )
    variants=lead_phone_variants(patient.phone)
    siblings=_phone_matched_profiles(patient.phone)
    sibling_ids=[item.pk for item in siblings] or [patient.pk]
    _hydrate_from_siblings(patient,siblings)

    _assert_patient_access(request,patient,profile)

    appointment_qs=(
        VisitAppointment.objects
        .filter(phone__in=variants)
        .select_related('branch','doctor_completed_by','created_by','lead')
        .order_by('-appointment_date','-appointment_time','-id')
    )
    appointments=list(appointment_qs[:100])
    appointment_ids=[item.pk for item in appointments]

    finance_qs=(
        FinancialTransaction.objects
        .filter(entry_type='inc')
        .filter(
            Q(appointment_id__in=appointment_ids)
            | Q(patient_ref__in=variants)
            | (Q(patient_ref=patient.crm_id) if patient.crm_id else Q(pk__in=[]))
        )
        .exclude(review_status='cancelled')
        .select_related('branch','appointment','recorded_by')
        .order_by('-occurred_at','-id')
    )
    approved_paid=finance_qs.filter(review_status='approved').aggregate(v=Sum('amount'))['v'] or Decimal('0')
    pending_paid=finance_qs.filter(review_status='pending').aggregate(v=Sum('amount'))['v'] or Decimal('0')

    leads=list(
        ReferralLead.objects.filter(phone__in=variants)
        .select_related('assigned_to__user','first_appointment_by','referrer')
        .order_by('-created_at')[:40]
    )
    sms=list(
        SmsMessageLog.objects.filter(Q(number__in=variants)|Q(appointment_id__in=appointment_ids))
        .select_related('appointment','created_by')
        .order_by('-created_at')[:50]
    )
    analyses=list(
        BodyAnalysisRecord.objects.filter(patient_id__in=sibling_ids)
        .select_related('recorded_by').order_by('-recorded_at','-id')[:48]
    )
    latest_analysis=analyses[0] if analyses else None
    oldest_analysis=analyses[-1] if analyses else None

    diets=list(
        PatientDietProgram.objects.filter(patient_id__in=sibling_ids)
        .select_related('appointment','prescribed_by')
        .order_by('-prescribed_at','-id')[:60]
    )
    devices=list(
        PatientDeviceProgram.objects.filter(patient_id__in=sibling_ids)
        .select_related('appointment','prescribed_by')
        .order_by('-prescribed_at','-id')[:60]
    )
    lipolytics=list(
        PatientLipolyticProgram.objects.filter(patient_id__in=sibling_ids)
        .select_related('appointment','prescribed_by')
        .order_by('-prescribed_at','-id')[:60]
    )
    notes=list(
        PatientCareNote.objects.filter(patient_id__in=sibling_ids)
        .select_related('appointment','author')
        .order_by('-created_at','-id')[:80]
    )
    ratings=list(
        PatientTeamRating.objects.filter(patient_id__in=sibling_ids)
        .select_related('author','author__profile')
        .order_by('-updated_at','-id')[:30]
    )
    rating_stats=PatientTeamRating.objects.filter(patient_id__in=sibling_ids).aggregate(
        overall=Avg('overall_score'),
        cooperation=Avg('cooperation_score'),
        purchase_capacity=Avg('purchase_capacity_score'),
    )
    my_rating=PatientTeamRating.objects.filter(patient=patient,author=request.user).first()
    device_sessions=list(
        DeviceSessionBooking.objects.filter(appointment_id__in=appointment_ids)
        .select_related('device','secondary_device','appointment','plan_item')
        .order_by('-starts_at')[:60]
    )

    # Visit matrix: visits are rows; tailored programs are columns.
    diets_by_appt={}
    devices_by_appt={}
    lipolytics_by_appt={}
    notes_by_appt={}
    for item in diets:
        if item.appointment_id:
            diets_by_appt.setdefault(item.appointment_id,[]).append(item)
    for item in devices:
        if item.appointment_id:
            devices_by_appt.setdefault(item.appointment_id,[]).append(item)
    for item in lipolytics:
        if item.appointment_id:
            lipolytics_by_appt.setdefault(item.appointment_id,[]).append(item)
    for item in notes:
        if item.appointment_id:
            notes_by_appt.setdefault(item.appointment_id,[]).append(item)

    visit_rows=[]
    chronological=list(reversed(appointments))
    for number,appt in enumerate(chronological,1):
        appt_diets=diets_by_appt.get(appt.pk,[])
        appt_devices=devices_by_appt.get(appt.pk,[])
        appt_lipos=lipolytics_by_appt.get(appt.pk,[])
        appt_notes=notes_by_appt.get(appt.pk,[])
        food=_join_text([item.diet_name for item in appt_diets])
        recommendations=_join_text(
            [item.recommendation_pack for item in appt_diets]
            + [item.note for item in appt_diets if item.note]
            + [item.body for item in appt_notes if item.note_type=='staff']
        )
        prescriptions=_join_text(
            [item.print_template for item in appt_diets if item.print_template]
            + [item.body for item in appt_notes if item.note_type in ('clinical','cem')]
        )
        treatment=_join_text(
            [f'{item.device_name}{(" · "+item.area) if item.area else ""}' for item in appt_devices]
            + [f'{item.protocol_name}{(" · "+item.area) if item.area else ""}' for item in appt_lipos]
        )
        if not any((food,recommendations,prescriptions,treatment)) and not appt.notes:
            continue
        visit_rows.append({
            'number':number,
            'appointment':appt,
            'food':food or '—',
            'recommendations':recommendations or '—',
            'prescriptions':prescriptions or '—',
            'treatment':treatment or '—',
        })

    first_appointment=appointment_qs.aggregate(v=Min('appointment_date'))['v']
    first_lead=ReferralLead.objects.filter(phone__in=variants).aggregate(v=Min('created_at'))['v']
    since_candidates=[item.created_at for item in siblings if item.created_at]
    if first_appointment:
        since_candidates.append(timezone.make_aware(
            datetime.combine(first_appointment,time.min),
            timezone.get_current_timezone(),
        ))
    if first_lead:
        since_candidates.append(first_lead)
    customer_since=min(since_candidates) if since_candidates else patient.created_at

    weight_delta=None
    if latest_analysis and oldest_analysis and latest_analysis.weight_kg is not None and oldest_analysis.weight_kg is not None:
        weight_delta=latest_analysis.weight_kg-oldest_analysis.weight_kg

    recorded_contact_count=ReferralLead.objects.filter(phone__in=variants).filter(
        Q(contact_result__gt='') | ~Q(status='new')
    ).count()

    context={
        'patient':patient,
        'can_view_full_phone':_can_view_full_phone(request,profile),
        'patient_phone_display':patient.phone if _can_view_full_phone(request,profile) else _masked_phone(patient.phone),
        'age':_age(patient.birth_date),
        'customer_since':customer_since,
        'appointments':appointments,
        'appointment_count':appointment_qs.count(),
        'visit_rows':visit_rows,
        'finance_rows':list(finance_qs[:50]),
        'approved_paid':approved_paid,
        'pending_paid':pending_paid,
        'leads':leads,
        'recorded_contact_count':recorded_contact_count,
        'sms_rows':sms,
        'sms_count':SmsMessageLog.objects.filter(Q(number__in=variants)|Q(appointment_id__in=appointment_ids)).count(),
        'analyses':analyses,
        'latest_analysis':latest_analysis,
        'weight_delta':weight_delta,
        'diets':diets,
        'devices':devices,
        'lipolytics':lipolytics,
        'notes':notes,
        'ratings':ratings,
        'rating_stats':rating_stats,
        'my_rating':my_rating,
        'can_capture_photo':profile.role in {'receptionist','admin','internal_manager'},
        'can_rate_patient':profile.role in {'call_center','receptionist','consultant','doctor','admin','internal_manager','manager'},
        'device_sessions':device_sessions,
        'linked_profile_count':len(siblings),
        'back_url':request.META.get('HTTP_REFERER') or reverse('dashboard'),
    }
    response=render(request,'core/patient_360.html',context)
    response['Cache-Control']='no-store, private'
    response['Pragma']='no-cache'
    return response


@login_required
def patient_360_send_sms(request, pk):
    profile=_profile(request)
    if request.method!='POST':
        return redirect('patient_360',pk=pk)
    patient=get_object_or_404(PatientProfile,pk=pk)
    _assert_patient_access(request,patient,profile)
    body=(request.POST.get('body') or '').strip()[:1200]
    if not body:
        messages.error(request,'متن پیامک را وارد کنید.')
        return redirect('patient_360',pk=patient.pk)
    number=normalize_lead_phone(patient.phone)
    try:
        send_sms(number,body,purpose='manual',created_by=request.user)
    except SmsGatewayError as exc:
        messages.error(request,f'ارسال پیامک ناموفق بود: {exc}')
    else:
        messages.success(request,f'پیامک برای {patient.full_name} ارسال شد؛ شماره موبایل نمایش داده نشد.')
    return redirect('patient_360',pk=patient.pk)


@login_required
def patient_360_photo(request, pk):
    profile=_profile(request)
    if profile.role not in {'receptionist','admin','internal_manager'}:
        raise PermissionDenied('ثبت عکس بیمار برای این نقش فعال نیست.')
    patient=get_object_or_404(PatientProfile,pk=pk)
    _assert_patient_access(request,patient,profile)
    if request.method!='POST':
        return redirect('patient_360',pk=patient.pk)
    photo=request.FILES.get('photo')
    if not photo:
        messages.error(request,'عکسی دریافت نشد.')
        return redirect('patient_360',pk=patient.pk)
    if photo.size>5*1024*1024:
        messages.error(request,'حجم عکس باید کمتر از ۵ مگابایت باشد.')
        return redirect('patient_360',pk=patient.pk)
    content_type=(getattr(photo,'content_type','') or '').lower()
    if content_type not in {'image/jpeg','image/png','image/webp'}:
        messages.error(request,'فرمت عکس باید JPG، PNG یا WEBP باشد.')
        return redirect('patient_360',pk=patient.pk)
    patient.photo=photo
    patient.save(update_fields=['photo','updated_at'])
    messages.success(request,'عکس بیمار در پرونده ذخیره شد.')
    return redirect('patient_360',pk=patient.pk)


@login_required
def patient_360_rating(request, pk):
    profile=_profile(request)
    if profile.role not in {'call_center','receptionist','consultant','doctor','admin','internal_manager','manager'}:
        raise PermissionDenied('امتیازدهی بیمار برای این نقش فعال نیست.')
    patient=get_object_or_404(PatientProfile,pk=pk)
    _assert_patient_access(request,patient,profile)
    if request.method!='POST':
        return redirect('patient_360',pk=patient.pk)

    def score(name):
        try:
            value=int(request.POST.get(name) or 3)
        except (TypeError,ValueError):
            value=3
        return max(1,min(5,value))

    rating,_created=PatientTeamRating.objects.update_or_create(
        patient=patient,
        author=request.user,
        defaults={
            'overall_score':score('overall_score'),
            'cooperation_score':score('cooperation_score'),
            'purchase_capacity_score':score('purchase_capacity_score'),
            'tags':(request.POST.get('tags') or '').strip()[:500],
            'note':(request.POST.get('note') or '').strip()[:1200],
        },
    )
    messages.success(request,'ارزیابی شما برای این بیمار ذخیره شد.')
    return redirect('patient_360',pk=patient.pk)


@login_required
def patient_360_from_lead(request, lead_id):
    profile=_profile(request)
    lead=get_object_or_404(ReferralLead.objects.select_related('assigned_to'),pk=lead_id)
    if profile.role=='call_center':
        if not (
            lead.assigned_to_id==profile.pk
            or lead.first_appointment_by_id==request.user.pk
            or lead.created_by_id==request.user.pk
        ):
            raise PermissionDenied('این لید در چرخه کاری شما قرار ندارد.')
    phone=normalize_lead_phone(lead.phone)
    if not phone:
        messages.error(request,'این لید شماره موبایل معتبر ندارد.')
        return redirect('call_center_lead',pk=lead.pk)
    patient=next(
        (item for item in _phone_matched_profiles(phone) if normalize_lead_phone(item.phone)==phone),
        None,
    )
    if not patient:
        patient=PatientProfile.objects.create(
            phone=phone,
            full_name=lead.full_name,
            created_by=request.user,
        )
    return redirect('patient_360',pk=patient.pk)
