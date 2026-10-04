from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum, Min
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .models import (
    BodyAnalysisRecord, DeviceSessionBooking, FinancialTransaction, PatientCareNote,
    PatientDeviceProgram, PatientDietProgram, PatientLipolyticProgram, PatientProfile,
    ReferralLead, SmsMessageLog, VisitAppointment, lead_phone_variants,
    normalize_lead_phone,
)


ALLOWED_ROLES={'admin','internal_manager','manager','doctor','consultant','receptionist'}


def _profile(request):
    profile=getattr(request.user,'profile',None)
    if not profile or profile.role not in ALLOWED_ROLES:
        raise PermissionDenied('دسترسی به پرونده ۳۶۰ بیمار برای این نقش فعال نیست.')
    return profile


def _age(birth_date):
    if not birth_date:
        return None
    today=timezone.localdate()
    return today.year-birth_date.year-((today.month,today.day)<(birth_date.month,birth_date.day))


def _patient_from_appointment(appointment, user):
    phone=normalize_lead_phone(appointment.phone)
    if not phone:
        return None
    patient,created=PatientProfile.objects.get_or_create(
        phone=phone,
        defaults={
            'full_name':appointment.full_name,
            'home_branch':appointment.branch,
            'created_by':user,
        },
    )
    changed=[]
    if appointment.full_name and patient.full_name!=appointment.full_name:
        patient.full_name=appointment.full_name
        changed.append('full_name')
    if not patient.home_branch_id and appointment.branch_id:
        patient.home_branch=appointment.branch
        changed.append('home_branch')
    if changed:
        changed.append('updated_at')
        patient.save(update_fields=changed)
    return patient


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
    if profile.role in {'manager','doctor','consultant','receptionist'} and profile.branch_id:
        if patient.home_branch_id and patient.home_branch_id!=profile.branch_id:
            # Historical appointments can still prove this patient belongs to the
            # current branch; avoid blocking valid cross-created profiles.
            if not VisitAppointment.objects.filter(
                branch_id=profile.branch_id,
                phone__in=lead_phone_variants(patient.phone),
            ).exists():
                raise PermissionDenied('این پرونده برای شعبه شما قابل مشاهده نیست.')

    variants=lead_phone_variants(patient.phone)
    appointment_qs=(
        VisitAppointment.objects
        .filter(phone__in=variants)
        .select_related('branch','doctor_completed_by','created_by','lead')
        .order_by('-appointment_date','-appointment_time','-id')
    )
    appointments=list(appointment_qs[:80])
    appointment_ids=[item.pk for item in appointments]

    finance_qs=(
        FinancialTransaction.objects
        .filter(entry_type='inc')
        .filter(
            Q(appointment_id__in=appointment_ids)
            | Q(patient_ref__in=variants)
            | Q(person_name__iexact=patient.full_name)
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
        .order_by('-created_at')[:30]
    )
    sms=list(
        SmsMessageLog.objects.filter(Q(number__in=variants)|Q(appointment_id__in=appointment_ids))
        .select_related('appointment','created_by')
        .order_by('-created_at')[:40]
    )
    analyses=list(patient.body_analyses.select_related('recorded_by').order_by('-recorded_at')[:36])
    latest_analysis=analyses[0] if analyses else None
    oldest_analysis=analyses[-1] if analyses else None

    diets=list(
        PatientDietProgram.objects.filter(patient=patient)
        .select_related('appointment','prescribed_by')
        .order_by('-prescribed_at')[:30]
    )
    devices=list(
        PatientDeviceProgram.objects.filter(patient=patient)
        .select_related('appointment','prescribed_by')
        .order_by('-prescribed_at')[:30]
    )
    lipolytics=list(
        PatientLipolyticProgram.objects.filter(patient=patient)
        .select_related('appointment','prescribed_by')
        .order_by('-prescribed_at')[:30]
    )
    notes=list(
        PatientCareNote.objects.filter(patient=patient)
        .select_related('appointment','author')
        .order_by('-created_at')[:40]
    )
    device_sessions=list(
        DeviceSessionBooking.objects.filter(appointment_id__in=appointment_ids)
        .select_related('device','secondary_device','appointment','plan_item')
        .order_by('-starts_at')[:40]
    )

    first_appointment=appointment_qs.aggregate(v=Min('appointment_date'))['v']
    first_lead=ReferralLead.objects.filter(phone__in=variants).aggregate(v=Min('created_at'))['v']
    since_candidates=[patient.created_at]
    if first_appointment:
        since_candidates.append(timezone.make_aware(
            timezone.datetime.combine(first_appointment,timezone.datetime.min.time()),
            timezone.get_current_timezone(),
        ))
    if first_lead:
        since_candidates.append(first_lead)
    customer_since=min(since_candidates) if since_candidates else patient.created_at

    weight_delta=None
    if latest_analysis and oldest_analysis and latest_analysis.weight_kg is not None and oldest_analysis.weight_kg is not None:
        weight_delta=latest_analysis.weight_kg-oldest_analysis.weight_kg

    call_outcomes=[lead for lead in leads if lead.contact_result or lead.status!='new']

    context={
        'patient':patient,
        'age':_age(patient.birth_date),
        'customer_since':customer_since,
        'appointments':appointments,
        'appointment_count':appointment_qs.count(),
        'finance_rows':list(finance_qs[:40]),
        'approved_paid':approved_paid,
        'pending_paid':pending_paid,
        'leads':leads,
        'recorded_contact_count':len(call_outcomes),
        'sms_rows':sms,
        'sms_count':SmsMessageLog.objects.filter(Q(number__in=variants)|Q(appointment_id__in=appointment_ids)).count(),
        'analyses':analyses,
        'latest_analysis':latest_analysis,
        'weight_delta':weight_delta,
        'diets':diets,
        'devices':devices,
        'lipolytics':lipolytics,
        'notes':notes,
        'device_sessions':device_sessions,
        'back_url':request.META.get('HTTP_REFERER') or reverse('dashboard'),
    }
    return render(request,'core/patient_360.html',context)
