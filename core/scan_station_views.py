from decimal import Decimal, InvalidOperation
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Q
from django.utils import timezone
from .models import PatientProfile, BodyAnalysisRecord, EmployeeProfile

FIELDS = [('weight_kg','وزن (kg)'),('inbody_score','امتیاز'),('skeletal_muscle_kg','عضلات (kg)'),('fat_kg','چربی (kg)'),('whr','نسبت دور کمر به باسن'),('visceral_fat','چربی احشایی')]

@login_required
def scan_station(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role not in ('scan_station','receptionist','admin','internal_manager','manager'):
        raise PermissionDenied
    branch = profile.branch
    if not branch and profile.role not in ('admin','internal_manager'):
        raise PermissionDenied('شعبه حساب اسکن مشخص نشده است.')
    patients = PatientProfile.objects.all()
    if branch:
        patients = patients.filter(home_branch=branch)
    patients = patients.order_by('-updated_at')[:100]
    staff = EmployeeProfile.objects.filter(user__is_active=True,is_active=True).exclude(role__in=['scan_station','referrer'])
    if branch:
        staff = staff.filter(branch=branch)
    staff = staff.select_related('user').order_by('user__first_name','user__last_name')
    default_staff = staff.filter(role='receptionist').first()
    if request.method == 'POST':
        patient = get_object_or_404(PatientProfile,pk=request.POST.get('patient_id'))
        if branch and patient.home_branch_id != branch.id:
            raise PermissionDenied
        operator = get_object_or_404(staff,pk=request.POST.get('operator_id'))
        values = {}
        try:
            for key,_ in FIELDS:
                raw=request.POST.get(key,'').strip()
                if not raw:
                    raise ValueError('تمام شش فاکتور الزامی است.')
                value=Decimal(raw)
                if not value.is_finite() or value < 0:
                    raise ValueError('مقادیر باید عدد مثبت یا صفر باشند.')
                values[key]=value
            if values['whr'] > 5:
                raise ValueError('نسبت دور کمر به باسن معتبر نیست.')
        except (InvalidOperation,ValueError) as exc:
            messages.error(request,str(exc) or 'مقادیر نامعتبر هستند.')
        else:
            BodyAnalysisRecord.objects.create(
                patient=patient, recorded_at=timezone.now(),
                weight_kg=values['weight_kg'],inbody_score=values['inbody_score'],
                skeletal_muscle_kg=values['skeletal_muscle_kg'],
                visceral_fat=values['visceral_fat'],
                measurements={'fat_kg':str(values['fat_kg']),'whr':str(values['whr']),
                              'scan_operator_id':operator.pk,'scan_operator_name':operator.user.get_full_name() or operator.user.username,
                              'scan_branch_id':branch.pk if branch else None},
                recorded_by=request.user)
            messages.success(request,'اسکن و آنالیز ثبت شد.')
            return redirect('scan_station')
    return render(request,'core/scan_station.html',{'patients':patients,'staff':staff,'default_staff':default_staff,'branch':branch,'fields':FIELDS})
