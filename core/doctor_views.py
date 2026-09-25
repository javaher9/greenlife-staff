from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone

from .call_center_identity import call_center_display_name
from .models import (
    BodyAnalysisRecord,
    InternalMessage,
    PatientCareNote,
    PatientDeviceProgram,
    PatientDietProgram,
    PatientLipolyticProgram,
    PatientProfile,
    ReferralLead,
    StaffNotification,
    VisitAppointment,
    Branch,
    normalize_lead_phone,
)


DIET_OPTIONS = (
    'رژیم کاهش وزن استاندارد',
    'رژیم کم‌کربوهیدرات',
    'رژیم مدیترانه‌ای',
)
RECOMMENDATION_OPTIONS = (
    'مراجعه اول',
    'یبوست',
    'مصرف آب و فیبر',
    'فعالیت بدنی و سبک زندگی',
)
PRINT_TEMPLATE_OPTIONS = (
    'نسخه استاندارد',
    'نسخه همراه توصیه‌ها',
    'نسخه پیگیری',
)
DEVICE_OPTIONS = (
    'CoolTech Define',
    'Double Define',
    'EM',
    'Super Lift',
)
BODY_AREAS = (
    'شکم و پهلو',
    'ران',
    'ساق',
    'باسن',
    'بازو',
    'سوتین لاین',
    'غبغب',
)


def _is_executive_doctor(user):
    return bool(
        getattr(user,'is_superuser',False)
        or (getattr(user,'username','') or '').lower() in settings.EXECUTIVE_USERNAMES
    )


def _doctor_required(view):
    @login_required
    def wrapper(request, *args, **kwargs):
        profile=getattr(request.user,'profile',None)
        if not profile or (profile.role!='doctor' and not _is_executive_doctor(request.user)):
            raise PermissionDenied('این بخش فقط برای پزشک فعال است.')
        return view(request,*args,**kwargs)
    return wrapper


def _age_on(birth_date):
    if not birth_date:
        return None
    today=timezone.localdate()
    return today.year-birth_date.year-((today.month,today.day)<(birth_date.month,birth_date.day))


def _ensure_patient(appointment, doctor):
    phone=normalize_lead_phone(appointment.phone)
    if not phone:
        return None
    defaults={
        'full_name':appointment.full_name,
        'home_branch':appointment.branch,
        'created_by':doctor,
    }
    patient,created=PatientProfile.objects.get_or_create(phone=phone,defaults=defaults)
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


def _appointment_flower(item):
    if not item or not item.lead_id:
        return ''
    if item.lead.first_appointment_by_id:
        return call_center_display_name(item.lead.first_appointment_by)
    if item.lead.assigned_to_id:
        return call_center_display_name(item.lead.assigned_to)
    return ''


def _appointment_row(item, now):
    if item.status=='cancelled':
        label='لغو شده'; tone='cancelled'
    elif item.care_stage=='consultant':
        label='ارسال به مشاور'; tone='consultant'
    elif item.care_stage=='payment':
        label='در انتظار پرداخت'; tone='payment'
    elif item.care_stage=='closed' or item.status=='completed':
        label='تکمیل شده'; tone='done'
    elif item.status=='arrived':
        label='در کلینیک'; tone='arrived'
    else:
        local_target=timezone.make_aware(
            datetime.combine(item.appointment_date,item.appointment_time),
            timezone.get_current_timezone(),
        )
        if local_target < now:
            label='زمان گذشته'; tone='late'
        else:
            label='در انتظار'; tone='waiting'
    owner=_appointment_flower(item)
    return {
        'item':item,
        'status_label':label,
        'status_tone':tone,
        'owner':owner,
    }


def _sparkline(values, width=180, height=52):
    values=[float(v) for v in values if v is not None]
    if not values:
        return ''
    if len(values)==1:
        return f'4,{height/2:.1f} {width-4},{height/2:.1f}'
    low=min(values); high=max(values)
    span=high-low or 1
    points=[]
    for index,value in enumerate(values):
        x=4+(width-8)*(index/(len(values)-1))
        y=4+(height-8)*(1-((value-low)/span))
        points.append(f'{x:.1f},{y:.1f}')
    return ' '.join(points)


def _metric_card(analyses, field, label, unit, tone):
    values=[getattr(item,field) for item in analyses if getattr(item,field) is not None]
    latest=values[-1] if values else None
    delta=None
    if len(values)>=2:
        try:
            delta=Decimal(latest)-Decimal(values[0])
        except (InvalidOperation,TypeError):
            delta=None
    return {
        'field':field,
        'label':label,
        'unit':unit,
        'tone':tone,
        'latest':latest,
        'delta':delta,
        'points':_sparkline(values),
    }


def _selected_appointment(request, appointments):
    raw=(request.POST.get('appointment_id') if request.method=='POST' else request.GET.get('appointment')) or ''
    if str(raw).isdigit():
        for item in appointments:
            if item.pk==int(raw):
                return item
    arrived=next((item for item in appointments if item.status=='arrived'),None)
    waiting=next((item for item in appointments if item.status=='booked'),None)
    return arrived or waiting or (appointments[0] if appointments else None)


def _redirect_to_appointment(appointment_id, branch_id=None):
    url=reverse('doctor_dashboard')
    parts=[]
    if branch_id:
        parts.append(f'branch={branch_id}')
    if appointment_id:
        parts.append(f'appointment={appointment_id}')
    return redirect(url+('?'+'&'.join(parts) if parts else ''))


@_doctor_required
def doctor_dashboard(request):
    profile=request.user.profile
    today=timezone.localdate()
    now=timezone.localtime()
    executive_doctor=_is_executive_doctor(request.user)
    branch_choices=Branch.objects.filter(is_active=True).order_by('name') if executive_doctor else Branch.objects.filter(pk=profile.branch_id)
    requested_branch=(request.POST.get('branch_id') if request.method=='POST' else request.GET.get('branch')) or ''
    branch=None
    if executive_doctor and str(requested_branch).isdigit():
        branch=branch_choices.filter(pk=int(requested_branch)).first()
    if branch is None:
        if profile.branch_id:
            branch=profile.branch
        elif executive_doctor:
            branch=(
                branch_choices.filter(name__icontains='نیاوران').first()
                or branch_choices.filter(name__icontains='نياوران').first()
                or branch_choices.first()
            )
        else:
            branch=branch_choices.first()

    appointment_qs=VisitAppointment.objects.none()
    if branch:
        appointment_qs=(
            VisitAppointment.objects
            .filter(branch=branch,appointment_date=today)
            .select_related('lead','lead__assigned_to__user','lead__first_appointment_by','branch')
            .order_by('appointment_time','id')
        )
    appointments=list(appointment_qs)
    selected=_selected_appointment(request,appointments)
    patient=_ensure_patient(selected,request.user) if selected else None

    if request.method=='POST':
        if not selected or not patient:
            messages.error(request,'ابتدا یکی از بیماران امروز را انتخاب کنید.')
            return _redirect_to_appointment(None,branch.pk if branch else None)

        action=(request.POST.get('action') or '').strip()
        if action=='send_to_consultant':
            if selected.status=='cancelled':
                messages.error(request,'نوبت لغوشده قابل ارسال به مشاور نیست.')
                return _redirect_to_appointment(selected.pk,branch.pk if branch else None)

            selected.care_stage='consultant'
            selected.doctor_completed_at=timezone.now()
            selected.doctor_completed_by=request.user
            if selected.status=='booked':
                selected.status='arrived'
            selected.save(update_fields=[
                'care_stage','doctor_completed_at','doctor_completed_by','status','updated_at'
            ])

            consultants=User.objects.filter(
                is_active=True,
                profile__is_active=True,
                profile__role='consultant',
                profile__branch=selected.branch,
            )
            doctor_name=request.user.get_full_name() or request.user.username
            plan_bits=[]
            diet_count=selected.diet_programs.count()
            device_count=selected.device_programs.count()
            lipo_count=selected.lipolytic_programs.count()
            if diet_count:
                plan_bits.append(f'{diet_count} برنامه غذایی')
            if device_count:
                plan_bits.append(f'{device_count} برنامه دستگاه')
            if lipo_count:
                plan_bits.append(f'{lipo_count} برنامه لیپولیتیک')
            plan_summary='، '.join(plan_bits) or 'پیشنهاد درمان ثبت‌شده'

            for consultant in consultants:
                StaffNotification.objects.create(
                    user=consultant,
                    title='بیمار جدید در انتظار مشاوره',
                    message=f'{selected.full_name} از طرف {doctor_name} ارسال شد · {plan_summary}',
                    notification_type='doctor_handoff',
                    related_date=timezone.localdate(),
                )

            messages.success(
                request,
                f'ویزیت {selected.full_name} پایان یافت و پرونده برای مشاور ارسال شد.'
            )
            return _redirect_to_appointment(selected.pk,branch.pk if branch else None)

        if action=='diet':
            diet=(request.POST.get('diet_name') or '').strip()
            if not diet:
                messages.error(request,'برنامه غذایی را انتخاب کنید.')
            else:
                PatientDietProgram.objects.create(
                    patient=patient,
                    appointment=selected,
                    diet_name=diet[:160],
                    recommendation_pack=(request.POST.get('recommendation_pack') or '').strip()[:160],
                    print_template=(request.POST.get('print_template') or '').strip()[:160],
                    note=(request.POST.get('note') or '').strip()[:2000],
                    prescribed_by=request.user,
                )
                messages.success(request,'برنامه غذایی و توصیه‌ها در پرونده ثبت شد.')
            return _redirect_to_appointment(selected.pk,branch.pk if branch else None)

        if action=='device':
            device=(request.POST.get('device_name') or '').strip()
            try:
                sessions=max(1,min(30,int(request.POST.get('sessions') or 1)))
            except (TypeError,ValueError):
                sessions=1
            if not device:
                messages.error(request,'دستگاه را انتخاب کنید.')
            else:
                PatientDeviceProgram.objects.create(
                    patient=patient,
                    appointment=selected,
                    device_name=device[:160],
                    area=(request.POST.get('area') or '').strip()[:120],
                    sessions_prescribed=sessions,
                    note=(request.POST.get('note') or '').strip()[:2000],
                    prescribed_by=request.user,
                )
                messages.success(request,'پیشنهاد دستگاه در پرونده ثبت شد.')
            return _redirect_to_appointment(selected.pk,branch.pk if branch else None)

        if action=='lipolytic':
            protocol=(request.POST.get('protocol_name') or 'لیپولیتیک').strip()
            try:
                sessions=max(1,min(20,int(request.POST.get('sessions') or 1)))
            except (TypeError,ValueError):
                sessions=1
            PatientLipolyticProgram.objects.create(
                patient=patient,
                appointment=selected,
                protocol_name=protocol[:160] or 'لیپولیتیک',
                area=(request.POST.get('area') or '').strip()[:120],
                sessions_prescribed=sessions,
                note=(request.POST.get('note') or '').strip()[:2000],
                prescribed_by=request.user,
            )
            messages.success(request,'برنامه لیپولیتیک در پرونده ثبت شد.')
            return _redirect_to_appointment(selected.pk,branch.pk if branch else None)

        if action=='clinical_note':
            body=(request.POST.get('body') or '').strip()
            if body:
                PatientCareNote.objects.create(
                    patient=patient,appointment=selected,author=request.user,note_type='clinical',body=body[:3000]
                )
                messages.success(request,'یادداشت پزشک ثبت شد.')
            return _redirect_to_appointment(selected.pk,branch.pk if branch else None)

    rows=[_appointment_row(item,now) for item in appointments]
    stats={
        'total':len(appointments),
        'arrived':sum(1 for item in appointments if item.status in ('arrived','completed')),
        'late':sum(1 for row in rows if row['status_tone']=='late'),
        'cancelled':sum(1 for item in appointments if item.status=='cancelled'),
    }

    analyses=[]
    metric_cards=[]
    diet_history=[]
    device_history=[]
    lipolytic_history=[]
    care_notes=[]
    if patient:
        analyses=list(patient.body_analyses.order_by('recorded_at','id')[:36])
        metric_cards=[
            _metric_card(analyses,'weight_kg','وزن','kg','violet'),
            _metric_card(analyses,'visceral_fat','چربی احشایی','','rose'),
            _metric_card(analyses,'inbody_score','امتیاز آنالیز','','indigo'),
            _metric_card(analyses,'skeletal_muscle_kg','عضله','kg','green'),
            _metric_card(analyses,'body_fat_percent','درصد چربی','%','amber'),
        ]
        diet_history=list(patient.diet_programs.all()[:6])
        device_history=list(patient.device_programs.all()[:6])
        lipolytic_history=list(patient.lipolytic_programs.all()[:6])
        care_notes=list(patient.care_notes.select_related('author')[:5])

    direct_messages=list(
        InternalMessage.objects.filter(
            Q(sender=request.user,recipient__isnull=False) |
            Q(recipient=request.user)
        )
        .select_related('sender','recipient')
        .order_by('-created_at')[:5]
    )

    patient_summary=None
    if patient:
        patient_summary={
            'name':patient.full_name,
            'age':_age_on(patient.birth_date),
            'height':patient.height_cm,
            'neighborhood':patient.neighborhood,
            'medical_history':patient.medical_history,
            'is_vip':patient.is_vip,
            'photo':patient.photo,
        }

    return render(request,'core/doctor/dashboard.html',{
        'doctor_profile':profile,
        'doctor_branch':branch,
        'doctor_branch_choices':branch_choices,
        'executive_doctor_mode':executive_doctor,
        'today':today,
        'appointment_rows':rows,
        'appointment_stats':stats,
        'selected_appointment':selected,
        'selected_flower':_appointment_flower(selected),
        'patient':patient,
        'patient_summary':patient_summary,
        'metric_cards':metric_cards,
        'analysis_count':len(analyses),
        'diet_history':diet_history,
        'device_history':device_history,
        'lipolytic_history':lipolytic_history,
        'care_notes':care_notes,
        'direct_messages':direct_messages,
        'diet_options':DIET_OPTIONS,
        'recommendation_options':RECOMMENDATION_OPTIONS,
        'print_template_options':PRINT_TEMPLATE_OPTIONS,
        'device_options':DEVICE_OPTIONS,
        'body_areas':BODY_AREAS,
        'current_visit_diet_count':selected.diet_programs.count() if selected else 0,
        'current_visit_device_count':selected.device_programs.count() if selected else 0,
        'current_visit_lipolytic_count':selected.lipolytic_programs.count() if selected else 0,
        'current_visit_note_count':selected.care_notes.count() if selected else 0,
    })
