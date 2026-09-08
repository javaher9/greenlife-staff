import math
import uuid
from datetime import date, datetime, timedelta
from django.http import JsonResponse
from django.conf import settings
from django.core.exceptions import PermissionDenied
from functools import wraps
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.db import transaction
from django.db.models import Count, Q, Sum
from django.utils import timezone
from .forms import ReportForm, TaskStatusForm, TaskForm, LeaveRequestForm, LeaveReviewForm, AnnouncementForm, BlackboardMessageForm, EmployeeCreateForm, EmployeeEditForm, AttendanceManualForm, KPIRecordForm, ScoreEventForm, WorkShiftForm, ShiftAssignmentForm, AttendanceCorrectionForm, AttendanceCorrectionReviewForm, EmployeeAvatarForm, EmployeeDocumentForm, ChecklistTemplateForm, ChecklistItemForm, PersonnelActionForm, PerformanceGoalForm, InternalRequestForm, ManagementEventForm, ManagerReportCommentForm, JobDutyTemplateForm, GuidelineForm, DeviceIssueForm, DeviceIssueReviewForm, ConsultantFinanceEntryForm, StaffLoginForm, StaffCredentialUpdateForm
from .models import Announcement, BlackboardMessage, DailyReport, Task, LeaveRequest, SOPDocument, EmployeeProfile, Attendance, KPIRecord, ScoreEvent, WorkShift, ShiftAssignment, Branch, BranchWorkSchedule, EmployeeWorkSchedule, AttendanceCorrectionRequest, StaffNotification, EmployeeDocument, ChecklistTemplate, ChecklistItem, ChecklistCompletion, PersonnelAction, PerformanceGoal, InternalRequest, AuditLog, ManagementEvent, CEOScoreSnapshot, JobDutyTemplate, Guideline, GuidelineAcknowledgement, DeviceIssue, FinancialTransaction, MeetingActionUpdate, StaffCredential, VisitAppointment
from .ai import analyze_finance_receipt, process_report
from .jalali import format_jalali, gregorian_to_jalali, jalali_to_gregorian, parse_jalali
from .reporting import day_summary, leaderboard, answer_query
from .operations import shift_rule, attendance_status_for, overtime_minutes, award_report, award_task, missing_report_days, auto_kpi, approve_correction, report_required, report_exists
from .smart_alerts import generate_smart_alerts
from .executive_engine import ceo_score, trend_alerts, calendar_events
from .credential_security import (
    change_desktop_password, change_mobile_pin, decrypt_secret,
    record_desktop_login, record_mobile_login, remember_desktop_password,
    verify_mobile_pin,
)

def role_of(user): return getattr(getattr(user,'profile',None),'role','employee')

MANAGEMENT_ROLES=('admin','internal_manager','manager')
FINANCE_ROLES=('admin','manager')
PERSONNEL_ROLES=('employee','call_center','consultant','receptionist')


def _is_mobile_request(request):
    """Keep the established dark personnel experience on phones."""
    if (request.META.get('HTTP_SEC_CH_UA_MOBILE') or '').strip() == '?1':
        return True
    ua=(request.META.get('HTTP_USER_AGENT') or '').lower()
    mobile_tokens=('iphone','ipod','mobile','windows phone','opera mini')
    return any(token in ua for token in mobile_tokens)


def _is_executive_user(user):
    return bool(
        getattr(user,'is_authenticated',False)
        and (getattr(user,'username','') or '').lower() in settings.EXECUTIVE_USERNAMES
    )


def executive_required(view):
    @wraps(view)
    @login_required
    def wrapper(request,*args,**kwargs):
        if not _is_executive_user(request.user):
            raise PermissionDenied('Executive workspace access denied.')
        return view(request,*args,**kwargs)
    return wrapper


def credential_admin_required(view):
    @wraps(view)
    @login_required
    def wrapper(request,*args,**kwargs):
        if not (request.user.is_superuser or _is_executive_user(request.user)):
            raise PermissionDenied('Credential administration access denied.')
        return view(request,*args,**kwargs)
    return wrapper

def _request_ip(request):
    forwarded=request.META.get('HTTP_X_FORWARDED_FOR','')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR') or None

def _attendance_audit(request, action, summary='', metadata=None, obj=None):
    """Best-effort audit logging; never blocks attendance if logging itself fails."""
    try:
        AuditLog.objects.create(
            actor=request.user if getattr(request,'user',None) and request.user.is_authenticated else None,
            action=action,
            path=request.path[:255],
            method=request.method[:10],
            object_type='Attendance',
            object_id=str(getattr(obj,'pk','') or ''),
            summary=(summary or '')[:250],
            metadata=metadata or {},
            ip_address=_request_ip(request),
        )
    except Exception:
        pass


_UNICODE_ESCAPES = {
    r'\u200c':'‌', r'\u200f':'‏', r'\u200e':'‎', r'\n':'\n', r'\t':'\t'
}
def normalize_ai_text(value):
    if not isinstance(value,str): return value
    out=value
    for raw,real in _UNICODE_ESCAPES.items():
        out=out.replace(raw,real)
    return out

def manager_required(view):
    @wraps(view)
    @login_required
    def wrapper(request,*args,**kwargs):
        if role_of(request.user) not in MANAGEMENT_ROLES:
            messages.error(request,'دسترسی مجاز نیست.')
            return redirect('dashboard')
        return view(request,*args,**kwargs)
    return wrapper

def standard_manager_required(view):
    @wraps(view)
    @login_required
    def wrapper(request,*args,**kwargs):
        if role_of(request.user) not in ('admin','manager'):
            messages.error(request,'این بخش برای مدیر داخلی فعال نیست.')
            return redirect('dashboard')
        return view(request,*args,**kwargs)
    return wrapper

def finance_required(view):
    @wraps(view)
    @login_required
    def wrapper(request,*args,**kwargs):
        if role_of(request.user) not in FINANCE_ROLES:
            messages.error(request,'بخش مالی برای نقش مدیر داخلی فعال نیست.')
            return redirect('dashboard')
        return view(request,*args,**kwargs)
    return wrapper

def consultant_required(view):
    @wraps(view)
    @login_required
    def wrapper(request,*args,**kwargs):
        if role_of(request.user)!='consultant':
            messages.error(request,'ثبت مالی فقط برای نقش مشاور فعال است.')
            return redirect('dashboard')
        if not getattr(request.user.profile,'branch_id',None):
            messages.error(request,'برای ثبت مالی باید شعبه مشاور مشخص باشد.')
            return redirect('dashboard')
        return view(request,*args,**kwargs)
    return wrapper

def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')

    mobile_login=_is_mobile_request(request)
    form=StaffLoginForm(request.POST or None,mobile=mobile_login)
    if request.method=='POST' and form.is_valid():
        raw_username=(form.cleaned_data.get('username') or '').strip()
        secret=form.cleaned_data.get('password') or ''
        matched=User.objects.filter(username__iexact=raw_username,is_active=True).order_by('id').first()
        user=None
        auth_error='نام کاربری یا رمز صحیح نیست.'

        if matched:
            if mobile_login:
                verified,status=verify_mobile_pin(matched,secret)
                if verified is True:
                    user=matched
                elif verified is None:
                    # Safe rollout: users without a mobile PIN keep using their
                    # existing desktop password on mobile until a PIN is assigned.
                    user=authenticate(request,username=matched.username,password=secret)
                elif status=='locked':
                    auth_error='ورود موبایل موقتاً قفل شده است. ده دقیقه دیگر دوباره امتحان کنید.'
            else:
                user=authenticate(request,username=matched.username,password=secret)

        if user:
            EmployeeProfile.objects.get_or_create(
                user=user,
                defaults={
                    'role':'admin' if user.is_superuser else 'employee',
                    'is_active':user.is_active,
                },
            )
            login(request,user,backend='django.contrib.auth.backends.ModelBackend')
            request.session['login_device']='mobile' if mobile_login else 'desktop'
            if mobile_login:
                record_mobile_login(user)
            else:
                record_desktop_login(user)
            return redirect(request.POST.get('next') or 'dashboard')

        form.add_error(None,auth_error)

    return render(request,'core/login.html',{
        'form':form,
        'mobile_login':mobile_login,
        'next':request.POST.get('next') or request.GET.get('next') or '',
    })

@credential_admin_required
def credential_settings(request):
    profiles=(
        EmployeeProfile.objects.exclude(role='referrer')
        .select_related('user','branch','user__staff_credential')
        .order_by('branch__name','user__last_name','user__first_name','user__username')
    )
    rows=[]
    for profile in profiles:
        credential=getattr(profile.user,'staff_credential',None)
        rows.append({
            'profile':profile,
            'credential':credential,
            'desktop_revealable':bool(credential and credential.desktop_password_cipher),
            'mobile_revealable':bool(credential and credential.mobile_pin_cipher),
        })
    response=render(request,'core/credential_settings.html',{'credential_rows':rows})
    response['Cache-Control']='no-store, private'
    response['Pragma']='no-cache'
    return response


@credential_admin_required
def credential_update(request,pk):
    profile=get_object_or_404(EmployeeProfile.objects.select_related('user','branch'),pk=pk)
    if request.method!='POST':
        return redirect('credential_settings')
    form=StaffCredentialUpdateForm(request.POST)
    if form.is_valid():
        desktop=form.cleaned_data.get('desktop_password') or ''
        mobile=form.cleaned_data.get('mobile_pin') or ''
        if desktop:
            change_desktop_password(profile.user,desktop,actor=request.user)
        if mobile:
            change_mobile_pin(profile.user,mobile,actor=request.user)
        AuditLog.objects.create(
            actor=request.user,action='credential_update',path=request.path,method='POST',
            object_type='User',object_id=str(profile.user_id),
            summary=f'Credential update for {profile.user.username}',
            metadata={'desktop_changed':bool(desktop),'mobile_changed':bool(mobile)},
            ip_address=_request_ip(request),
        )
        messages.success(request,f'دسترسی‌های {profile.user.get_full_name() or profile.user.username} به‌روزرسانی شد.')
    else:
        messages.error(request,'رمزها ذخیره نشدند: '+ ' '.join(
            msg for field in form.errors.values() for msg in field
        ))
    return redirect('credential_settings')


@credential_admin_required
def credential_reveal(request,pk,kind):
    if request.method!='POST':
        return JsonResponse({'ok':False,'error':'POST required'},status=405)
    profile=get_object_or_404(EmployeeProfile.objects.select_related('user'),pk=pk)
    credential=getattr(profile.user,'staff_credential',None)
    cipher=''
    if credential:
        if kind=='desktop':
            cipher=credential.desktop_password_cipher
        elif kind=='mobile':
            cipher=credential.mobile_pin_cipher
    if kind not in ('desktop','mobile'):
        return JsonResponse({'ok':False,'error':'invalid kind'},status=400)
    secret=decrypt_secret(cipher)
    if not secret:
        return JsonResponse({'ok':False,'error':'این رمز هنوز برای نمایش ذخیره نشده است.'},status=404)
    AuditLog.objects.create(
        actor=request.user,action='credential_reveal',path=request.path,method='POST',
        object_type='User',object_id=str(profile.user_id),
        summary=f'{kind} credential revealed for {profile.user.username}',
        metadata={'kind':kind},
        ip_address=_request_ip(request),
    )
    response=JsonResponse({'ok':True,'secret':secret})
    response['Cache-Control']='no-store, private'
    response['Pragma']='no-cache'
    return response


@credential_admin_required
def impersonate_start(request,pk):
    if request.method!='POST':
        return redirect('credential_settings')
    target_profile=get_object_or_404(EmployeeProfile.objects.select_related('user'),pk=pk,is_active=True)
    target=target_profile.user
    if target.is_superuser or target_profile.role=='admin':
        messages.error(request,'برای امنیت، ورود آزمایشی به حساب مدیر سیستم از این صفحه مجاز نیست.')
        return redirect('credential_settings')
    original_id=request.user.pk
    AuditLog.objects.create(
        actor=request.user,action='impersonation_start',path=request.path,method='POST',
        object_type='User',object_id=str(target.pk),
        summary=f'View as {target.username}',metadata={},
        ip_address=_request_ip(request),
    )
    login(request,target,backend='django.contrib.auth.backends.ModelBackend')
    request.session['impersonator_user_id']=original_id
    request.session['impersonator_started_at']=timezone.now().isoformat()
    request.session['login_device']='desktop'
    return redirect('dashboard')


@login_required
def impersonate_return(request):
    if request.method!='POST':
        return redirect('dashboard')
    original_id=request.session.get('impersonator_user_id')
    if not original_id:
        return redirect('dashboard')
    original=User.objects.filter(pk=original_id,is_active=True).first()
    if not original or not (original.is_superuser or _is_executive_user(original)):
        logout(request)
        return redirect('login')
    target_id=request.user.pk
    AuditLog.objects.create(
        actor=original,action='impersonation_end',path=request.path,method='POST',
        object_type='User',object_id=str(target_id),
        summary=f'Returned from view-as user {target_id}',metadata={},
        ip_address=_request_ip(request),
    )
    login(request,original,backend='django.contrib.auth.backends.ModelBackend')
    request.session.pop('impersonator_user_id',None)
    request.session.pop('impersonator_started_at',None)
    request.session['login_device']='desktop'
    return redirect('credential_settings')


def logout_view(request): logout(request); return redirect('login')

@login_required
def dashboard(request):
    role=role_of(request.user)
    if _is_executive_user(request.user):
        return redirect('executive_workspace')
    if role=='receptionist' and not _is_mobile_request(request):
        profile=getattr(request.user,'profile',None)
        today_local=timezone.localdate()
        jalali_year,jalali_month,jalali_day=gregorian_to_jalali(
            today_local.year,today_local.month,today_local.day
        )
        weekday_names={0:'دوشنبه',1:'سه‌شنبه',2:'چهارشنبه',3:'پنجشنبه',4:'جمعه',5:'شنبه',6:'یکشنبه'}
        jalali_month_names=['فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور','مهر','آبان','آذر','دی','بهمن','اسفند']
        jalali_dashboard_date=f"{weekday_names[today_local.weekday()]} {jalali_day} {jalali_month_names[jalali_month-1]} {jalali_year}"
        receptionist_tasks=Task.objects.filter(
            assigned_to=request.user
        ).exclude(status='done').order_by('due_date','-priority','id')[:5]
        receptionist_notifications=StaffNotification.objects.filter(
            user=request.user,is_read=False
        ).order_by('-created_at')[:4]
        attendance_today=Attendance.objects.filter(
            user=request.user,date=today_local
        ).first()
        receptionist_branch=getattr(profile,'branch',None)
        if receptionist_branch:
            receptionist_appointments=VisitAppointment.objects.filter(
                branch=receptionist_branch,appointment_date=today_local
            ).exclude(status='cancelled').order_by('appointment_time')
        else:
            receptionist_appointments=VisitAppointment.objects.none()
        receptionist_appointment_count=receptionist_appointments.count()
        receptionist_arrived_count=receptionist_appointments.filter(
            status__in=('arrived','completed')
        ).count()
        return render(request,'core/receptionist_dashboard.html',{
            'role':role,
            'profile':profile,
            'receptionist_tasks':receptionist_tasks,
            'receptionist_task_count':Task.objects.filter(
                assigned_to=request.user
            ).exclude(status='done').count(),
            'receptionist_notifications':receptionist_notifications,
            'notification_count':StaffNotification.objects.filter(
                user=request.user,is_read=False
            ).count(),
            'attendance_today':attendance_today,
            'today_shift':shift_rule(request.user,today_local),
            'jalali_dashboard_date':jalali_dashboard_date,
            'receptionist_appointments':receptionist_appointments,
            'receptionist_appointment_count':receptionist_appointment_count,
            'receptionist_arrived_count':receptionist_arrived_count,
        })
    if role=='call_center' and not _is_mobile_request(request):
        return redirect('call_center_dashboard')
    if role=='referrer':
        return redirect('referral_dashboard')
    if role in MANAGEMENT_ROLES:
        return redirect('branch_live_dashboard')
    user_tasks=Task.objects.filter(assigned_to=request.user)
    tasks=user_tasks.order_by('status','due_date')[:8]
    profile=getattr(request.user,'profile',None)
    announcements=Announcement.objects.filter(is_active=True).filter(Q(branch__isnull=True)|Q(branch=getattr(profile,'branch',None))).order_by('-created_at')[:4]
    blackboard_qs=BlackboardMessage.objects.filter(is_active=True)
    profile_branch=getattr(profile,'branch',None)
    blackboard=(blackboard_qs.filter(branch=profile_branch).first() if profile_branch else None) or blackboard_qs.filter(branch__isnull=True).first()
    counts=user_tasks.values('status').annotate(n=Count('id')); stats={x['status']:x['n'] for x in counts}
    pending_leave=LeaveRequest.objects.filter(user=request.user,status='pending').count()
    attendance_today=Attendance.objects.filter(user=request.user,date=timezone.localdate()).first()
    today_local=timezone.localdate()
    jalali_year,jalali_month,jalali_day=gregorian_to_jalali(
        today_local.year,today_local.month,today_local.day
    )
    jalali_month_start=date(*jalali_to_gregorian(jalali_year,jalali_month,1))
    report_end=today_local-timedelta(days=1)
    if report_end < jalali_month_start:
        missing_reports=[]
    else:
        month_days=(report_end-jalali_month_start).days+1
        missing_reports=missing_report_days(request.user,days=month_days,end=report_end)
    notifications_qs=StaffNotification.objects.filter(user=request.user,is_read=False)
    notifications=notifications_qs[:5]
    notification_count=notifications_qs.count()
    today_shift=shift_rule(request.user,timezone.localdate())
    finance_stats={}
    if role=='consultant':
        finance_qs=FinancialTransaction.objects.filter(source='manual',recorded_by=request.user)
        finance_stats={
            'today':finance_qs.filter(created_at__date=today_local).count(),
            'pending':finance_qs.filter(review_status='pending').count(),
            'correction':finance_qs.filter(review_status='needs_correction').count(),
            'last':finance_qs.order_by('-created_at').first(),
        }

    # Real employee-dashboard status (no mock values).
    today_report_exists=DailyReport.objects.filter(
        user=request.user,
        created_at__date=today_local,
    ).exists()

    checklist_templates=_checklist_templates_for(request.user)
    checklist_item_ids=list(
        ChecklistItem.objects.filter(template__in=checklist_templates).values_list('id',flat=True)
    )
    checklist_total=len(checklist_item_ids)
    checklist_done=ChecklistCompletion.objects.filter(
        user=request.user,
        date=today_local,
        item_id__in=checklist_item_ids,
        is_done=True,
    ).count() if checklist_item_ids else 0

    task_total=user_tasks.count()
    task_done=user_tasks.filter(status='done').count()
    task_progress=round(task_done*100/task_total) if task_total else 100
    checklist_progress=round(checklist_done*100/checklist_total) if checklist_total else 100
    overall_progress=round((task_progress+checklist_progress+(100 if today_report_exists else 0))/3)

    weekday_names={0:'دوشنبه',1:'سه‌شنبه',2:'چهارشنبه',3:'پنجشنبه',4:'جمعه',5:'شنبه',6:'یکشنبه'}
    jalali_month_names=['فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور','مهر','آبان','آذر','دی','بهمن','اسفند']
    jalali_dashboard_date=f"{weekday_names[today_local.weekday()]} {jalali_day} {jalali_month_names[jalali_month-1]} {jalali_year}"

    role=role_of(request.user)
    manager_stats={}
    if role in MANAGEMENT_ROLES:
        qs=Task.objects.all()
        if role=='manager': qs=qs.filter(assigned_to__profile__branch=getattr(profile,'branch',None))
        manager_stats={'all_tasks':qs.count(),'overdue':qs.filter(due_date__lt=timezone.localdate()).exclude(status='done').count(),'pending_leave':LeaveRequest.objects.filter(status='pending').count()}
    return render(request,'core/dashboard.html',{
        'tasks':tasks,
        'announcements':announcements,
        'blackboard':blackboard,
        'stats':stats,
        'pending_leave':pending_leave,
        'manager_stats':manager_stats,
        'role':role,
        'attendance_today':attendance_today,
        'missing_reports':missing_reports,
        'notifications':notifications,
        'notification_count':notification_count,
        'today_shift':today_shift,
        'finance_stats':finance_stats,
        'today_report_exists':today_report_exists,
        'checklist_total':checklist_total,
        'checklist_done':checklist_done,
        'checklist_progress':checklist_progress,
        'task_total':task_total,
        'task_done':task_done,
        'task_progress':task_progress,
        'overall_progress':overall_progress,
        'jalali_dashboard_date':jalali_dashboard_date,
    })

@login_required
def report_create(request):
    # A stable token is rendered with the form and sent back on POST.
    # If the browser/network retries the same submission, return the already
    # created report instead of inserting another DailyReport row.
    submission_id=(request.POST.get('submission_id') or '').strip() if request.method=='POST' else uuid.uuid4().hex

    if request.method=='POST' and submission_id:
        existing=DailyReport.objects.filter(client_submission_id=submission_id,user=request.user).first()
        if existing:
            messages.info(request,'این گزارش قبلاً ثبت شده بود؛ از ثبت تکراری جلوگیری شد.')
            return redirect('report_detail',pk=existing.pk)

    form=ReportForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False)
        obj.user=request.user
        obj.branch=getattr(getattr(request.user,'profile',None),'branch',None)
        obj.client_submission_id=submission_id or uuid.uuid4().hex
        obj.save()
        award_report(request.user,timezone.localdate())

        if request.POST.get('process_ai')=='1':
            try:
                ok,msg=process_report(obj); messages.success(request,msg) if ok else messages.warning(request,msg)
            except Exception as e:
                obj.process_status='failed'; obj.save(update_fields=['process_status']); messages.error(request,f'گزارش ذخیره شد، ولی پردازش هوش مصنوعی انجام نشد: {e}')
        else:
            messages.success(request,'گزارش با موفقیت ثبت شد.')
        return redirect('report_detail',pk=obj.pk)

    if not submission_id:
        submission_id=uuid.uuid4().hex
    return render(request,'core/report_form.html',{'form':form,'submission_id':submission_id})

@login_required
def report_list(request):
    qs=DailyReport.objects.select_related('user','branch').order_by('-created_at'); role=role_of(request.user)
    if role in PERSONNEL_ROLES: qs=qs.filter(user=request.user)
    elif role=='manager': qs=qs.filter(branch=getattr(request.user.profile,'branch',None))
    return render(request,'core/report_list.html',{'reports':qs[:200]})

@login_required
def report_detail(request,pk):
    obj=get_object_or_404(DailyReport,pk=pk)
    role=role_of(request.user)
    if role in PERSONNEL_ROLES and obj.user_id!=request.user.id:
        messages.error(request,'دسترسی مجاز نیست.')
        return redirect('report_list')
    if role=='manager' and getattr(obj.user.profile,'branch_id',None)!=getattr(request.user.profile,'branch_id',None):
        messages.error(request,'دسترسی مجاز نیست.')
        return redirect('report_list')

    # Clean escaped Unicode sequences for correct Persian rendering.
    obj.text=normalize_ai_text(obj.text)
    obj.transcript=normalize_ai_text(obj.transcript)
    obj.ai_summary=normalize_ai_text(obj.ai_summary)
    obj.follow_up=normalize_ai_text(obj.follow_up)
    obj.manager_comment=normalize_ai_text(obj.manager_comment)

    comment_form=None
    if role in MANAGEMENT_ROLES:
        comment_form=ManagerReportCommentForm(request.POST or None,instance=obj)
        if request.method=='POST' and request.POST.get('action')=='manager_comment' and comment_form.is_valid():
            target=comment_form.save(commit=False)
            target.manager_comment=normalize_ai_text(target.manager_comment)
            target.manager_comment_by=request.user
            target.manager_comment_at=timezone.now()
            target.save(update_fields=['manager_comment','manager_comment_by','manager_comment_at'])
            messages.success(request,'کامنت مدیر ثبت شد.')
            return redirect('report_detail',pk=obj.pk)

    return render(request,'core/report_detail.html',{'report':obj,'comment_form':comment_form})

@login_required
def task_list(request):
    role=role_of(request.user)
    qs=Task.objects.select_related('assigned_to','meeting_action').order_by('status','due_date')
    if role in PERSONNEL_ROLES: qs=qs.filter(assigned_to=request.user)
    elif role=='manager': qs=qs.filter(assigned_to__profile__branch=request.user.profile.branch)
    return render(request,'core/task_list.html',{'tasks':qs,'can_manage':role in MANAGEMENT_ROLES})

@login_required
def my_task_list(request):
    qs=Task.objects.filter(assigned_to=request.user).select_related('assigned_to','meeting_action').order_by('status','due_date','-priority')
    return render(request,'core/task_list.html',{'tasks':qs,'can_manage':False})

@login_required
def task_update(request,pk):
    task=get_object_or_404(Task,pk=pk,assigned_to=request.user); form=TaskStatusForm(request.POST or None,instance=task)
    if request.method=='POST' and form.is_valid():
        obj=form.save()
        meeting_action=getattr(obj,'meeting_action',None)
        if meeting_action:
            before=meeting_action.status
            requested=obj.status
            meeting_action.status={'todo':'todo','doing':'doing','done':'awaiting_approval'}[requested]
            meeting_action.save(update_fields=['status','updated_at'])
            MeetingActionUpdate.objects.create(
                action=meeting_action,user=request.user,previous_status=before,
                new_status=meeting_action.status,
                note='از بخش کارهای من به‌روزرسانی شد.',
            )
            if requested=='done':
                obj.status='doing'; obj.save(update_fields=['status','updated_at'])
                messages.success(request,'انجام کار ثبت شد و برای تأیید مدیر داخلی ارسال شد.')
            else:
                messages.success(request,'پیشرفت مصوبه به‌روزرسانی شد.')
        else:
            award_task(obj); messages.success(request,'وضعیت وظیفه به‌روزرسانی شد.')
        if obj.created_by_id and obj.created_by_id!=request.user.id and _is_executive_user(obj.created_by):
            actor=request.user.get_full_name() or request.user.username
            StaffNotification.objects.create(
                user=obj.created_by,
                title=f'بروزرسانی کار: {obj.title[:120]}',
                message=f'{actor} وضعیت کار را به «{obj.get_status_display()}» تغییر داد.',
                notification_type='task_update',
                related_date=obj.due_date or timezone.localdate(),
            )
        return redirect('my_task_list' if role_of(request.user) in MANAGEMENT_ROLES else 'task_list')
    return render(request,'core/task_update.html',{'form':form,'task':task})

@manager_required
def task_create(request):
    form=TaskForm(request.POST or None)
    if role_of(request.user)=='manager': form.fields['assigned_to'].queryset=User.objects.filter(profile__branch=request.user.profile.branch,profile__is_active=True)
    elif role_of(request.user)=='internal_manager': form.fields['assigned_to'].queryset=User.objects.filter(profile__role__in=PERSONNEL_ROLES,profile__is_active=True)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False); obj.created_by=request.user; obj.save(); messages.success(request,'وظیفه ایجاد شد.'); return redirect('task_list')
    return render(request,'core/generic_form.html',{'form':form,'title':'تعریف وظیفه جدید','button':'ثبت وظیفه'})

@login_required
def announcement_list(request):
    profile=getattr(request.user,'profile',None)
    qs=Announcement.objects.filter(is_active=True)
    if role_of(request.user) not in ('admin','internal_manager'):
        qs=qs.filter(Q(branch__isnull=True)|Q(branch=getattr(profile,'branch',None)))
    qs=qs.order_by('-created_at')
    return render(request,'core/announcement_list.html',{'announcements':qs,'can_manage':role_of(request.user) in MANAGEMENT_ROLES})

@manager_required
def announcement_create(request):
    form=AnnouncementForm(request.POST or None)
    if role_of(request.user)=='manager':
        form.fields['branch'].queryset=form.fields['branch'].queryset.filter(pk=request.user.profile.branch_id); form.fields['branch'].initial=request.user.profile.branch
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False); obj.created_by=request.user; obj.save(); messages.success(request,'اطلاعیه منتشر شد.'); return redirect('announcement_list')
    return render(request,'core/generic_form.html',{'form':form,'title':'اطلاعیه جدید','button':'انتشار'})

@manager_required
def blackboard_manage(request):
    qs=BlackboardMessage.objects.select_related('branch','created_by')
    if role_of(request.user)=='manager':
        qs=qs.filter(branch=request.user.profile.branch)
    return render(request,'core/blackboard_manage.html',{'blackboards':qs})

@manager_required
def blackboard_edit(request,pk=None):
    item=get_object_or_404(BlackboardMessage,pk=pk) if pk else None
    role=role_of(request.user)
    if item and role=='manager' and item.branch_id!=request.user.profile.branch_id:
        messages.error(request,'دسترسی به پیام این شعبه مجاز نیست.')
        return redirect('blackboard_manage')
    form=BlackboardMessageForm(request.POST or None,instance=item)
    if role=='manager':
        form.fields['branch'].queryset=form.fields['branch'].queryset.filter(pk=request.user.profile.branch_id)
        form.fields['branch'].initial=request.user.profile.branch
        form.fields['branch'].required=True
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False)
        if role=='manager': obj.branch=request.user.profile.branch
        if not obj.created_by_id: obj.created_by=request.user
        obj.save()
        messages.success(request,'پیام تخته‌سیاه ذخیره و برای پرسنل منتشر شد.' if obj.is_active else 'پیام تخته‌سیاه ذخیره شد.')
        return redirect('blackboard_manage')
    return render(request,'core/generic_form.html',{
        'form':form,'title':'ویرایش تخته‌سیاه' if item else 'پیام جدید تخته‌سیاه','button':'ذخیره و انتشار',
    })

@login_required
def leave_list(request):
    role=role_of(request.user); qs=LeaveRequest.objects.select_related('user').order_by('-created_at')
    if role in PERSONNEL_ROLES: qs=qs.filter(user=request.user)
    elif role=='manager': qs=qs.filter(user__profile__branch=request.user.profile.branch)
    return render(request,'core/leave_list.html',{'requests':qs,'can_review':role in MANAGEMENT_ROLES})

@login_required
def leave_create(request):
    form=LeaveRequestForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False); obj.user=request.user; obj.save(); messages.success(request,'درخواست ثبت شد.'); return redirect('leave_list')
    return render(request,'core/generic_form.html',{'form':form,'title':'درخواست جدید','button':'ارسال درخواست'})

@manager_required
def leave_review(request,pk):
    obj=get_object_or_404(LeaveRequest,pk=pk)
    if role_of(request.user)=='manager' and getattr(obj.user.profile,'branch_id',None)!=request.user.profile.branch_id: return redirect('leave_list')
    form=LeaveReviewForm(request.POST or None,instance=obj)
    if request.method=='POST' and form.is_valid():
        item=form.save(commit=False); item.reviewed_by=request.user; item.save(); messages.success(request,'درخواست بررسی شد.'); return redirect('leave_list')
    return render(request,'core/generic_form.html',{'form':form,'title':'بررسی درخواست','button':'ثبت نتیجه'})

@login_required
def sop_list(request):
    profile=getattr(request.user,'profile',None)
    qs=SOPDocument.objects.filter(is_active=True).filter(Q(branch__isnull=True)|Q(branch=getattr(profile,'branch',None))).filter(Q(job_title='')|Q(job_title=getattr(profile,'job_title',''))).order_by('title')
    return render(request,'core/sop_list.html',{'documents':qs})

@manager_required
def employee_list(request):
    role=role_of(request.user)
    qs=EmployeeProfile.objects.exclude(role='referrer').select_related('user','branch').order_by('branch__name','user__last_name')
    if role=='manager': qs=qs.filter(branch=request.user.profile.branch)
    elif role=='internal_manager': qs=qs.filter(role__in=PERSONNEL_ROLES)
    return render(request,'core/employee_list.html',{
        'employees':qs,
        'can_manage':role in MANAGEMENT_ROLES,
    })

@manager_required
def employee_create(request):
    form=EmployeeCreateForm(request.POST or None)
    if role_of(request.user)=='manager':
        form.fields['branch'].queryset=form.fields['branch'].queryset.filter(pk=request.user.profile.branch_id); form.fields['branch'].initial=request.user.profile.branch; form.fields['role'].choices=[('employee','کارمند')]
    elif role_of(request.user)=='internal_manager':
        form.fields['role'].choices=[('employee','کارمند'),('call_center','کال‌سنتر'),('consultant','مشاور')]
    if request.method=='POST' and form.is_valid():
        d=form.cleaned_data; user=User.objects.create_user(username=d['username'],password=d['password'],first_name=d['first_name'],last_name=d['last_name'])
        EmployeeProfile.objects.update_or_create(user=user,defaults={
            'branch':d['branch'],'role':d['role'],
            'job_title':d['job_title'] or ('کارشناس کال‌سنتر' if d['role']=='call_center' else 'مشاور' if d['role']=='consultant' else 'منشی' if d['role']=='receptionist' else ''),
            'employee_code':d['employee_code'] or None,'phone':d['phone'],
            'birth_date':d.get('birth_date'),'is_active':user.is_active,
        })
        remember_desktop_password(user,d['password'],actor=request.user)
        if d.get('mobile_pin'):
            change_mobile_pin(user,d['mobile_pin'],actor=request.user)
        messages.success(request,'کارمند ایجاد شد.'); return redirect('employee_list')
    return render(request,'core/generic_form.html',{'form':form,'title':'افزودن کارمند','button':'ساخت حساب'})

@manager_required
def employee_edit(request,pk):
    employee=get_object_or_404(EmployeeProfile.objects.select_related('user','branch','shift_group'),pk=pk)
    if not _employee_access(request,employee):
        messages.error(request,'به این پرسنل دسترسی ندارید.')
        return redirect('employee_list')
    form=EmployeeEditForm(request.POST or None,employee=employee)
    if role_of(request.user)=='manager':
        form.fields['branch'].queryset=form.fields['branch'].queryset.filter(pk=request.user.profile.branch_id)
        form.fields['role'].choices=[('employee','کارمند')]
        form.fields['shift_group'].queryset=form.fields['shift_group'].queryset.filter(branch=request.user.profile.branch)
    elif role_of(request.user)=='internal_manager':
        form.fields['role'].choices=[('employee','کارمند'),('call_center','کال‌سنتر'),('consultant','مشاور')]
    if request.method=='POST' and form.is_valid():
        with transaction.atomic():
            form.save()
            if form.cleaned_data.get('new_password'):
                remember_desktop_password(employee.user,form.cleaned_data['new_password'],actor=request.user)
        messages.success(request,'مشخصات پرسنل به‌روزرسانی شد.')
        return redirect('employee_file',pk=pk)
    return render(request,'core/employee_management_form.html',{
        'form':form,'employee':employee,'title':'ویرایش مشخصات',
        'subtitle':'اطلاعات هویتی، شغلی، تماس، بیمه و شیفت این پرسنل را به‌روزرسانی کنید.',
        'button':'ذخیره تغییرات','form_kind':'edit',
    })

@login_required
def profile_view(request):
    profile=getattr(request.user,'profile',None)
    form=EmployeeAvatarForm(request.POST or None,request.FILES or None,instance=profile) if profile else None
    if request.method=='POST' and form and form.is_valid():
        form.save()
        messages.success(request,'عکس پروفایل به‌روزرسانی شد.')
        return redirect('profile')
    today_shift=shift_rule(request.user,timezone.localdate()) if profile else None
    return render(request,'core/profile.html',{
        'profile':profile,
        'avatar_form':form,
        'today_shift':today_shift,
    })

@manager_required
def employee_avatar_edit(request,pk):
    employee=get_object_or_404(EmployeeProfile.objects.select_related('user','branch'),pk=pk)
    if not _employee_access(request,employee):
        messages.error(request,'به این پرسنل دسترسی ندارید.')
        return redirect('employee_list')
    form=EmployeeAvatarForm(request.POST or None,request.FILES or None,instance=employee)
    if request.method=='POST' and form.is_valid():
        form.save()
        messages.success(request,'عکس پرسنل به‌روزرسانی شد.')
        return redirect('employee_list')
    return render(request,'core/employee_avatar_form.html',{'form':form,'employee':employee})


def health_check(request):
    return JsonResponse({"status":"ok","service":"GreenLife Staff API","api_version":"1.0"})

@login_required
def attendance(request):
    today=timezone.localdate()
    profile=getattr(request.user,'profile',None)
    branch=getattr(profile,'branch',None)
    record=Attendance.objects.filter(user=request.user,date=today).first()

    def verify_location():
        """Return (ok, message, metadata). GPS is required only when branch geofence is enabled."""
        if not branch or not branch.geofence_enabled:
            return True, '', {'status':'legacy'}
        if branch.latitude is None or branch.longitude is None:
            return False, 'موقعیت شعبه هنوز توسط مدیر تنظیم نشده است.', {'status':'unavailable'}
        try:
            lat=float(request.POST.get('latitude',''))
            lon=float(request.POST.get('longitude',''))
            accuracy=float(request.POST.get('accuracy',''))
        except (TypeError,ValueError):
            return False, 'برای ثبت ورود باید دسترسی موقعیت مکانی را فعال کنید.', {'status':'unavailable'}

        # Reject malformed/impossible location values before distance calculation.
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0) or accuracy <= 0:
            return False, 'اطلاعات موقعیت مکانی معتبر نیست. GPS را خاموش و روشن کنید و دوباره امتحان کنید.', {
                'status':'unavailable','lat':lat,'lon':lon,'accuracy':accuracy
            }

        # Reject very imprecise fixes; otherwise a user could appear inside a large uncertainty circle.
        if accuracy > 200:
            return False, f'دقت GPS کافی نیست ({int(accuracy)} متر). کنار پنجره یا فضای باز دوباره امتحان کنید.', {
                'status':'low_accuracy','lat':lat,'lon':lon,'accuracy':accuracy
            }

        # Haversine distance, meters.
        r=6371000.0
        lat1,lon1=math.radians(float(branch.latitude)),math.radians(float(branch.longitude))
        lat2,lon2=math.radians(lat),math.radians(lon)
        dlat,dlon=lat2-lat1,lon2-lon1
        a=math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlon/2)**2
        distance=r*(2*math.atan2(math.sqrt(a),math.sqrt(1-a)))
        allowed=float(branch.attendance_radius_m) + min(accuracy,50.0)
        meta={'status':'verified' if distance <= allowed else 'outside',
              'lat':lat,'lon':lon,'accuracy':accuracy,'distance':round(distance)}
        if distance > allowed:
            return False, f'شما حدود {int(distance)} متر از شعبه فاصله دارید؛ ثبت ورود فقط داخل محدوده مجاز است.', meta
        return True, '', meta

    if request.method=='POST':
        action=request.POST.get('action')
        if action=='checkin':
            # Verify BEFORE creating today's record so failed attempts do not create phantom attendance.
            ok,msg,meta=verify_location()
            if not ok:
                _attendance_audit(
                    request,'attendance_location_rejected',msg,
                    {'action':'checkin','branch_id':getattr(branch,'id',None),**meta}
                )
                messages.error(request,msg)
                return redirect('attendance')
            record,_=Attendance.objects.get_or_create(
                user=request.user,date=today,defaults={'branch':branch}
            )
            now=timezone.now()
            if not record.check_in:
                record.check_in=now
                record.status=attendance_status_for(request.user,today,now)
                record.check_in_location_status=meta.get('status','legacy')
                if meta.get('lat') is not None:
                    record.check_in_latitude=meta['lat']
                    record.check_in_longitude=meta['lon']
                    record.check_in_accuracy_m=meta.get('accuracy')
                    record.check_in_distance_m=meta.get('distance')
                if record.status=='present' and not ScoreEvent.objects.filter(
                    user=request.user,event_date=today,reason='attendance'
                ).exists():
                    ScoreEvent.objects.create(
                        user=request.user,points=5,reason='attendance',description='حضور به‌موقع'
                    )
                record.save()
                _attendance_audit(
                    request,'attendance_checkin','ثبت ورود',
                    {
                        'branch_id':getattr(branch,'id',None),
                        'location_status':record.check_in_location_status,
                        'distance_m':record.check_in_distance_m,
                        'accuracy_m':record.check_in_accuracy_m,
                        'server_time':record.check_in.isoformat() if record.check_in else None,
                    },record
                )
                messages.success(request,'ورود شما با تأیید موقعیت ثبت شد.' if branch and branch.geofence_enabled else 'ورود شما ثبت شد.')
            else:
                messages.info(request,'ورود امروز قبلاً ثبت شده است.')
        elif action=='checkout':
            record=Attendance.objects.filter(user=request.user,date=today).first()
            if not record or not record.check_in:
                messages.error(request,'ابتدا ورود را ثبت کنید.')
            elif not record.check_out:
                # When geofence is enabled, checkout must also happen inside the branch radius.
                ok,msg,meta=verify_location()
                if not ok:
                    _attendance_audit(
                        request,'attendance_location_rejected','خروج ثبت نشد: '+msg,
                        {'action':'checkout','branch_id':getattr(branch,'id',None),**meta},record
                    )
                    messages.error(request,'خروج ثبت نشد: '+msg)
                    return redirect('attendance')
                record.check_out=timezone.now()
                record.save()
                _attendance_audit(
                    request,'attendance_checkout','ثبت خروج',
                    {
                        'branch_id':getattr(branch,'id',None),
                        'location_status':meta.get('status'),
                        'distance_m':meta.get('distance'),
                        'accuracy_m':meta.get('accuracy'),
                        'server_time':record.check_out.isoformat() if record.check_out else None,
                    },record
                )
                messages.success(request,'خروج شما با تأیید موقعیت ثبت شد.' if branch and branch.geofence_enabled else 'خروج شما ثبت شد.')
            else:
                messages.info(request,'خروج امروز قبلاً ثبت شده است.')
        return redirect('attendance')

    recent=Attendance.objects.filter(user=request.user).order_by('-date')[:31]
    return render(request,'core/attendance.html',{
        'record':record,'recent':recent,'today':today,
        'today_shift':shift_rule(request.user,today),'overtime':overtime_minutes(record),
        'geofence_enabled':bool(branch and branch.geofence_enabled),
        'geofence_radius':getattr(branch,'attendance_radius_m',None),
    })

@manager_required
def attendance_team(request):
    role=role_of(request.user); profile=getattr(request.user,'profile',None)
    date_value=request.GET.get('date')
    try: selected=parse_jalali(date_value) if date_value else timezone.localdate()
    except ValueError: selected=timezone.localdate()
    users=User.objects.filter(profile__is_active=True).select_related('profile','profile__branch')
    records=Attendance.objects.filter(date=selected).select_related('user','branch')
    if role=='manager':
        users=users.filter(profile__branch=profile.branch); records=records.filter(branch=profile.branch)
    recmap={r.user_id:r for r in records}
    rows=[(u,recmap.get(u.id)) for u in users.order_by('profile__branch__name','last_name','first_name')]
    summary={'employees':len(rows),'present':sum(1 for _,r in rows if r and r.check_in),'late':sum(1 for _,r in rows if r and r.status=='late'),'missing':sum(1 for _,r in rows if not r or not r.check_in)}
    return render(request,'core/attendance_team.html',{'rows':rows,'selected':selected,'summary':summary})

@manager_required
def attendance_edit(request,pk):
    obj=get_object_or_404(Attendance,pk=pk)
    if role_of(request.user)=='manager' and obj.branch_id!=request.user.profile.branch_id: return redirect('attendance_team')
    if role_of(request.user)=='internal_manager' and obj.user.profile.role not in PERSONNEL_ROLES: return redirect('attendance_team')
    form=AttendanceManualForm(request.POST or None,instance=obj)
    if role_of(request.user)=='manager': form.fields['user'].queryset=User.objects.filter(profile__branch=request.user.profile.branch)
    elif role_of(request.user)=='internal_manager': form.fields['user'].queryset=User.objects.filter(profile__role__in=PERSONNEL_ROLES,profile__is_active=True)
    if request.method=='POST' and form.is_valid():
        before={
            'user_id':obj.user_id,'date':str(obj.date),
            'check_in':obj.check_in.isoformat() if obj.check_in else None,
            'check_out':obj.check_out.isoformat() if obj.check_out else None,
            'status':obj.status,
        }
        changed=form.save(commit=False)
        changed.check_in_location_status='manual'
        changed.save()
        after={
            'user_id':changed.user_id,'date':str(changed.date),
            'check_in':changed.check_in.isoformat() if changed.check_in else None,
            'check_out':changed.check_out.isoformat() if changed.check_out else None,
            'status':changed.status,
        }
        _attendance_audit(request,'attendance_manual_edit','اصلاح دستی حضور و غیاب',{'before':before,'after':after},changed)
        messages.success(request,'رکورد حضور و غیاب اصلاح شد.')
        return redirect('attendance_team')
    return render(request,'core/generic_form.html',{'form':form,'title':'اصلاح حضور و غیاب','button':'ذخیره'})

@manager_required
def attendance_create(request):
    employee=None
    employee_pk=request.GET.get('employee')
    if employee_pk:
        employee=_employee_or_redirect(request,employee_pk)
        if employee is None:
            return redirect('employee_list')
    form=AttendanceManualForm(request.POST or None,initial={'user':employee.user} if employee else None)
    if role_of(request.user)=='manager': form.fields['user'].queryset=User.objects.filter(profile__branch=request.user.profile.branch)
    elif role_of(request.user)=='internal_manager': form.fields['user'].queryset=User.objects.filter(profile__role__in=PERSONNEL_ROLES,profile__is_active=True)
    if employee:
        form.fields['user'].disabled=True
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False)
        if employee:
            obj.user=employee.user
        obj.branch=getattr(getattr(obj.user,'profile',None),'branch',None)
        obj.check_in_location_status='manual'
        obj.save()
        _attendance_audit(
            request,'attendance_manual_create','ثبت دستی حضور و غیاب',
            {
                'user_id':obj.user_id,'date':str(obj.date),
                'check_in':obj.check_in.isoformat() if obj.check_in else None,
                'check_out':obj.check_out.isoformat() if obj.check_out else None,
                'status':obj.status,
            },obj
        )
        messages.success(request,'رکورد حضور و غیاب ثبت شد.')
        if employee:
            return redirect('employee_attendance',pk=employee.pk)
        return redirect('attendance_team')
    title='ثبت دستی حضور و غیاب'
    if employee:
        title+=f' برای {employee.user.get_full_name() or employee.user.username}'
    return render(request,'core/generic_form.html',{'form':form,'title':title,'button':'ثبت'})

@login_required
def attendance_api_today(request):
    rec=Attendance.objects.filter(user=request.user,date=timezone.localdate()).first()
    return JsonResponse({'date':str(timezone.localdate()),'check_in':rec.check_in.isoformat() if rec and rec.check_in else None,'check_out':rec.check_out.isoformat() if rec and rec.check_out else None,'status':rec.status if rec else None})


@manager_required
def analytics_dashboard(request):
    q=request.GET.get('q','')
    result=answer_query(request.user,q) if q else None
    summary=day_summary(request.user)
    board=leaderboard(request.user)[:10]
    return render(request,'core/analytics.html',{'summary':summary,'board':board,'query':q,'result':result})

@manager_required
def kpi_list(request):
    qs=KPIRecord.objects.select_related('user').all()
    if role_of(request.user)=='manager': qs=qs.filter(user__profile__branch=request.user.profile.branch)
    return render(request,'core/kpi_list.html',{'records':qs[:100]})

@manager_required
def kpi_create(request):
    form=KPIRecordForm(request.POST or None)
    if role_of(request.user)=='manager': form.fields['user'].queryset=User.objects.filter(profile__branch=request.user.profile.branch,profile__is_active=True)
    elif role_of(request.user)=='internal_manager': form.fields['user'].queryset=User.objects.filter(profile__role__in=PERSONNEL_ROLES,profile__is_active=True)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False); obj.created_by=request.user; obj.save()
        ScoreEvent.objects.create(user=obj.user,points=max(0,int(obj.score//10)),reason='kpi',description=f'KPI: {obj.title}',event_date=obj.period_end,created_by=request.user)
        messages.success(request,'KPI ثبت و امتیاز آن اعمال شد.'); return redirect('kpi_list')
    return render(request,'core/generic_form.html',{'form':form,'title':'ثبت KPI','button':'ثبت'})

@manager_required
def score_create(request):
    form=ScoreEventForm(request.POST or None)
    if role_of(request.user)=='manager': form.fields['user'].queryset=User.objects.filter(profile__branch=request.user.profile.branch,profile__is_active=True)
    elif role_of(request.user)=='internal_manager': form.fields['user'].queryset=User.objects.filter(profile__role__in=PERSONNEL_ROLES,profile__is_active=True)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False); obj.created_by=request.user; obj.save(); messages.success(request,'امتیاز ثبت شد.'); return redirect('analytics_dashboard')
    return render(request,'core/generic_form.html',{'form':form,'title':'امتیاز تشویقی/اصلاحی','button':'ثبت امتیاز'})

def _api_manager(request):
    import os
    key=os.getenv('STAFF_REPORT_API_KEY','')
    if key and request.headers.get('X-Staff-API-Key')==key: return True
    return request.user.is_authenticated and role_of(request.user) in MANAGEMENT_ROLES

def management_attendance_summary_api(request):
    if not _api_manager(request): return JsonResponse({'error':'unauthorized'},status=401)
    day=timezone.localdate()
    raw=request.GET.get('date')
    if raw:
        try: day=parse_jalali(raw)
        except ValueError: return JsonResponse({'error':'invalid jalali date; example: 1405/05/24'},status=400)
    data=day_summary(request.user,day) if request.user.is_authenticated else _api_day_summary_all(day)
    return JsonResponse(data,json_dumps_params={'ensure_ascii':False})

def _api_day_summary_all(day):
    from types import SimpleNamespace
    # API-key access is system-wide/admin scope.
    admin=User.objects.filter(profile__role='admin').first() or User.objects.filter(is_superuser=True).first()
    if admin: return day_summary(admin,day)
    records=Attendance.objects.filter(date=day).select_related('user','branch')
    rows=[{'id':r.user_id,'name':r.user.get_full_name() or r.user.username,'branch':r.branch.name if r.branch else None,'check_in':timezone.localtime(r.check_in).strftime('%H:%M') if r.check_in else None,'check_out':timezone.localtime(r.check_out).strftime('%H:%M') if r.check_out else None,'status':r.status,'status_fa':r.get_status_display()} for r in records]
    late=[x for x in rows if x['status']=='late']
    return {'date':format_jalali(day),'gregorian_date':str(day),'employees':len(rows),'present':sum(1 for x in rows if x['check_in']),'late':len(late),'missing':0,'late_people':late,'missing_people':[],'rows':rows}

def management_query_api(request):
    if not _api_manager(request): return JsonResponse({'error':'unauthorized'},status=401)
    q=request.GET.get('q','')
    if request.user.is_authenticated: data=answer_query(request.user,q)
    else:
        admin=User.objects.filter(profile__role='admin').first() or User.objects.filter(is_superuser=True).first()
        if not admin: return JsonResponse({'error':'no admin user configured'},status=503)
        data=answer_query(admin,q)
    return JsonResponse(data,json_dumps_params={'ensure_ascii':False})

@finance_required
def finance_dashboard(request):
    from .finance import finance_summary
    from .models import IntegrationSyncLog
    day=timezone.localdate(); raw=request.GET.get('date')
    if raw:
        try: day=parse_jalali(raw)
        except ValueError: messages.error(request,'تاریخ شمسی نامعتبر است.')
    branch=None
    if role_of(request.user)=='manager': branch=request.user.profile.branch
    summary=finance_summary(day,branch)
    logs=IntegrationSyncLog.objects.all()[:5]
    entries=FinancialTransaction.objects.filter(source='manual').select_related('branch','recorded_by')
    if role_of(request.user)=='manager': entries=entries.filter(branch=request.user.profile.branch)
    return render(request,'core/finance_dashboard.html',{
        'summary':summary,'logs':logs,'selected':day,'manual_entries':entries[:100],
    })

@consultant_required
def finance_entry(request):
    profile=request.user.profile
    initial={'entry_type':'inc'}
    requested_appointment=(request.GET.get('appointment') or '').strip()
    if requested_appointment.isdigit():
        initial['appointment']=requested_appointment
        initial['sale_origin']='afsariyeh'
    form=ConsultantFinanceEntryForm(
        request.POST or None,request.FILES or None,
        consultant_profile=profile,initial=initial,
    )
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False)
        tx_date=form.cleaned_data['date']
        local_now=timezone.localtime()
        naive_time=local_now.time().replace(tzinfo=None)
        obj.occurred_at=timezone.make_aware(datetime.combine(tx_date,naive_time))
        obj.branch=profile.branch
        obj.source='manual'
        obj.review_status='pending'
        obj.analysis_status='pending'
        obj.recorded_by=request.user
        appointment=form.cleaned_data.get('appointment')
        obj.appointment=appointment
        obj.sale_origin='afsariyeh' if appointment else 'branch_walk_in'
        if appointment:
            obj.person_name=appointment.full_name
        obj.patient_ref=obj.person_name
        obj.service=obj.get_sale_reason_display() if obj.sale_reason else obj.service
        obj.account_heading=obj.service
        obj.receipt_original_size=getattr(form,'receipt_original_size',0)
        obj.receipt_compressed_size=getattr(form,'receipt_compressed_size',0)
        obj.raw_data={
            'entry_channel':'staff_consultant',
            'sale_origin':obj.sale_origin,
            'appointment_id':appointment.pk if appointment else None,
            'lead_id':appointment.lead_id if appointment else None,
            'call_center_user_id':appointment.created_by_id if appointment else None,
        }
        with transaction.atomic():
            obj.save()
            if appointment:
                if appointment.status!='completed':
                    appointment.status='completed'
                    appointment.save(update_fields=['status','updated_at'])
                if appointment.lead_id and appointment.lead.status!='won':
                    appointment.lead.status='won'
                    appointment.lead.save(update_fields=['status','updated_at'])
            AuditLog.objects.create(
                actor=request.user,action='finance_entry',path=request.path,method='POST',
                object_type='FinancialTransaction',object_id=str(obj.pk),
                summary=f'ثبت مالی مشاور برای {obj.person_name}'[:250],
                metadata={
                    'amount':str(obj.amount),'branch_id':obj.branch_id,'status':obj.review_status,
                    'sale_origin':obj.sale_origin,'sale_reason':obj.sale_reason,
                    'appointment_id':obj.appointment_id,
                    'receipt_original_size':obj.receipt_original_size,
                    'receipt_compressed_size':obj.receipt_compressed_size,
                },
                ip_address=_request_ip(request),
            )
        messages.success(request,'تراکنش ثبت شد و برای بررسی مالی ارسال شد.')
        ok,analysis_message=analyze_finance_receipt(obj)
        if ok: messages.success(request,analysis_message)
        else: messages.warning(request,analysis_message+' ثبت مالی شما محفوظ است و مدیر می‌تواند تحلیل را دوباره اجرا کند.')
        return redirect('finance_entry')
    entries=FinancialTransaction.objects.filter(
        source='manual',recorded_by=request.user,
    ).select_related('branch').order_by('-created_at')[:50]
    pending_appointments=form.fields['appointment'].queryset[:30]
    return render(request,'core/finance_entry.html',{
        'form':form,'entries':entries,'pending_appointments':pending_appointments,
    })

@finance_required
def finance_entry_review(request,pk,action):
    if request.method!='POST': return redirect('finance_dashboard')
    entry=get_object_or_404(FinancialTransaction,pk=pk,source='manual')
    if role_of(request.user)=='manager' and entry.branch_id!=request.user.profile.branch_id:
        messages.error(request,'این تراکنش مربوط به شعبه شما نیست.')
        return redirect('finance_dashboard')
    status_map={'approve':'approved','correction':'needs_correction','cancel':'cancelled'}
    if action not in status_map:
        messages.error(request,'عملیات نامعتبر است.')
        return redirect('finance_dashboard')
    before=entry.review_status
    entry.review_status=status_map[action]
    entry.reviewed_by=request.user
    entry.reviewed_at=timezone.now()
    entry.review_note=(request.POST.get('review_note') or '').strip()[:300]
    entry.save(update_fields=['review_status','reviewed_by','reviewed_at','review_note'])
    AuditLog.objects.create(
        actor=request.user,action='finance_review',path=request.path,method='POST',
        object_type='FinancialTransaction',object_id=str(entry.pk),
        summary=f'وضعیت مالی از {before} به {entry.review_status}'[:250],
        metadata={'before':before,'after':entry.review_status},ip_address=_request_ip(request),
    )
    if entry.recorded_by:
        StaffNotification.objects.create(
            user=entry.recorded_by,title='نتیجه بررسی ثبت مالی',
            message=f'تراکنش {entry.person_name} به وضعیت «{entry.get_review_status_display()}» تغییر کرد.',
            notification_type='finance_review',related_date=timezone.localdate(),
        )
    messages.success(request,'وضعیت تراکنش به‌روزرسانی شد.')
    return redirect('finance_dashboard')

@finance_required
def finance_entry_delete(request,pk):
    if request.method!='POST':
        return redirect('finance_dashboard')
    if role_of(request.user)!='admin':
        raise PermissionDenied('حذف تراکنش فقط برای ادمین مجاز است.')
    entry=get_object_or_404(
        FinancialTransaction.objects.select_related('branch','recorded_by'),
        pk=pk,source='manual',
    )
    entry_id=entry.pk
    receipt_name=entry.receipt_image.name if entry.receipt_image else ''
    receipt_storage=entry.receipt_image.storage if receipt_name else None
    snapshot={
        'amount':str(entry.amount),
        'entry_type':entry.entry_type,
        'person_name':entry.person_name,
        'branch_id':entry.branch_id,
        'branch':entry.branch.name if entry.branch_id else '',
        'recorded_by_id':entry.recorded_by_id,
        'review_status':entry.review_status,
        'receipt_name':receipt_name,
    }
    with transaction.atomic():
        AuditLog.objects.create(
            actor=request.user,action='finance_delete',path=request.path,method='POST',
            object_type='FinancialTransaction',object_id=str(entry_id),
            summary=f'حذف تراکنش تکراری {entry.person_name or entry_id}'[:250],
            metadata=snapshot,ip_address=_request_ip(request),
        )
        entry.delete()
        if receipt_storage and receipt_name:
            transaction.on_commit(lambda: receipt_storage.delete(receipt_name))
    messages.success(request,'تراکنش تکراری حذف شد و سابقه حذف در گزارش مدیریتی باقی ماند.')
    return redirect('finance_dashboard')

@finance_required
def finance_entry_analyze(request,pk):
    if request.method!='POST': return redirect('finance_dashboard')
    entry=get_object_or_404(FinancialTransaction,pk=pk,source='manual')
    if role_of(request.user)=='manager' and entry.branch_id!=request.user.profile.branch_id:
        messages.error(request,'این تراکنش مربوط به شعبه شما نیست.')
        return redirect('finance_dashboard')
    entry.analysis_status='pending'; entry.analysis_error=''
    entry.save(update_fields=['analysis_status','analysis_error'])
    ok,message=analyze_finance_receipt(entry)
    if ok: messages.success(request,message)
    else: messages.warning(request,message)
    AuditLog.objects.create(
        actor=request.user,action='finance_receipt_analysis',path=request.path,method='POST',
        object_type='FinancialTransaction',object_id=str(entry.pk),summary=message[:250],
        metadata={'analysis_status':entry.analysis_status},ip_address=_request_ip(request),
    )
    return redirect('finance_dashboard')

@finance_required
def finance_sync(request):
    if request.method!='POST': return redirect('finance_dashboard')
    if role_of(request.user)!='admin': messages.error(request,'همگام‌سازی CRM فقط برای مدیر سیستم مجاز است.'); return redirect('finance_dashboard')
    try:
        from .finance import sync_crm
        result=sync_crm(); messages.success(request,f"همگام‌سازی انجام شد: {result['imported']} جدید، {result['updated']} به‌روزرسانی.")
    except Exception as e: messages.error(request,f'خطا در اتصال CRM: {e}')
    return redirect('finance_dashboard')

def management_finance_summary_api(request):
    if not _api_manager(request): return JsonResponse({'error':'unauthorized'},status=401)
    if request.user.is_authenticated and role_of(request.user)=='internal_manager':
        return JsonResponse({'error':'finance access denied'},status=403)
    from .finance import finance_summary
    day=timezone.localdate(); raw=request.GET.get('date')
    if raw:
        try: day=parse_jalali(raw)
        except ValueError: return JsonResponse({'error':'invalid jalali date; example: 1405/05/24'},status=400)
    branch=None
    if request.user.is_authenticated and role_of(request.user)=='manager': branch=request.user.profile.branch
    data=finance_summary(day,branch)
    data['total']=str(data['total'])
    for group in ('by_branch','by_payment'):
        for row in data[group]: row['total']=str(row['total'])
    return JsonResponse(data,json_dumps_params={'ensure_ascii':False})

@login_required
def notifications_list(request):
    qs=StaffNotification.objects.filter(user=request.user)
    if request.method=='POST':
        qs.filter(is_read=False).update(is_read=True); messages.success(request,'اعلان‌ها خوانده شدند.'); return redirect('notifications')
    return render(request,'core/notifications.html',{'notifications':qs[:100]})

@manager_required
def shift_list(request):
    shifts=WorkShift.objects.select_related('branch').filter(is_active=True)
    assignments=ShiftAssignment.objects.select_related('user','shift','shift__branch').order_by('-date')
    if role_of(request.user)=='manager':
        shifts=shifts.filter(branch=request.user.profile.branch)
        assignments=assignments.filter(user__profile__branch=request.user.profile.branch)
    return render(request,'core/shift_list.html',{'shifts':shifts,'assignments':assignments[:100]})

@manager_required
def shift_create(request):
    form=WorkShiftForm(request.POST or None)
    if role_of(request.user)=='manager':
        form.fields['branch'].queryset=form.fields['branch'].queryset.filter(pk=request.user.profile.branch_id)
        form.fields['branch'].initial=request.user.profile.branch
    if request.method=='POST' and form.is_valid():
        form.save(); messages.success(request,'شیفت ایجاد شد.'); return redirect('shift_list')
    return render(request,'core/generic_form.html',{'form':form,'title':'تعریف شیفت','button':'ثبت شیفت'})

@manager_required
def shift_assign(request):
    form=ShiftAssignmentForm(request.POST or None)
    if role_of(request.user)=='manager':
        form.fields['user'].queryset=User.objects.filter(profile__branch=request.user.profile.branch,profile__is_active=True)
        form.fields['shift'].queryset=WorkShift.objects.filter(branch=request.user.profile.branch,is_active=True)
    elif role_of(request.user)=='internal_manager':
        form.fields['user'].queryset=User.objects.filter(profile__role__in=PERSONNEL_ROLES,profile__is_active=True)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False); obj.created_by=request.user; obj.save(); messages.success(request,'شیفت روزانه تخصیص داده شد.'); return redirect('shift_list')
    return render(request,'core/generic_form.html',{'form':form,'title':'تخصیص شیفت','button':'ثبت تخصیص'})

@manager_required
def shift_today_bulk(request):
    """Manage today's exception and versioned weekly schedules from one safe screen."""
    role=role_of(request.user)
    if role not in ('admin','internal_manager'):
        messages.error(request,'تنظیم برنامه کاری فقط برای مدیر سیستم و مدیر داخلی فعال است.')
        return redirect('dashboard')
    day=timezone.localdate()
    branches=Branch.objects.filter(is_active=True).order_by('name')
    branch_id=request.POST.get('branch') or request.GET.get('branch')
    try: branch_id=int(branch_id) if branch_id else None
    except (TypeError,ValueError): branch_id=None
    selected_branch=branches.filter(pk=branch_id).first() if branch_id else branches.first()

    users=User.objects.none()
    if selected_branch:
        users=User.objects.filter(
        is_active=True,profile__is_active=True,profile__role__in=PERSONNEL_ROLES,
        profile__branch=selected_branch,
        ).select_related(
            'profile','profile__branch','profile__shift_group','profile__shift_group__default_shift',
        ).order_by('first_name','last_name','username')

    scoped_users={user.pk:user for user in users}
    weekday_order=[(5,'شنبه'),(6,'یکشنبه'),(0,'دوشنبه'),(1,'سه‌شنبه'),(2,'چهارشنبه'),(3,'پنجشنبه'),(4,'جمعه')]

    def parse_weekly_plan(prefix):
        plan=[]; errors=[]
        for weekday,label in weekday_order:
            is_working=request.POST.get(f'{prefix}_working_{weekday}')=='1'
            start_time=end_time=None
            if is_working:
                start_raw=(request.POST.get(f'{prefix}_start_{weekday}') or '').strip()
                end_raw=(request.POST.get(f'{prefix}_end_{weekday}') or '').strip()
                try:
                    start_time=datetime.strptime(start_raw,'%H:%M').time()
                    end_time=datetime.strptime(end_raw,'%H:%M').time()
                except ValueError:
                    errors.append(f'ساعت شروع و پایان {label} کامل یا معتبر نیست.')
            plan.append((weekday,is_working,start_time,end_time))
        return plan,errors

    def replace_weekly_rule(model,lookup,weekday,is_working,start_time,end_time):
        active=model.objects.filter(
            **lookup,weekday=weekday,effective_from__lte=day,
        ).filter(Q(effective_until__isnull=True)|Q(effective_until__gte=day)).order_by('-effective_from','-pk').first()
        if active and active.effective_from<day:
            active.effective_until=day-timedelta(days=1)
            active.save(update_fields=['effective_until','updated_at'])
        obj,_=model.objects.update_or_create(
            **lookup,weekday=weekday,effective_from=day,
            defaults={
                'is_working':is_working,
                'start_time':start_time if is_working else None,
                'end_time':end_time if is_working else None,
                'effective_until':None,
                'created_by':request.user,
            },
        )
        obj.full_clean()
        obj.save()

    if request.method=='POST':
        action=request.POST.get('action','save_today')
        if not selected_branch:
            messages.error(request,'شعبه معتبر انتخاب نشده است.')
        elif action=='save_branch_weekly':
            plan,errors=parse_weekly_plan('branch')
            if errors:
                for error in errors: messages.error(request,error)
            else:
                with transaction.atomic():
                    for values in plan:
                        replace_weekly_rule(BranchWorkSchedule,{'branch':selected_branch},*values)
                    _attendance_audit(request,'branch_weekly_schedule',summary=f'برنامه هفتگی شعبه {selected_branch} تنظیم شد',metadata={'branch_id':selected_branch.pk,'effective_from':day.isoformat()})
                messages.success(request,f'برنامه هفتگی {selected_branch} از امروز برای کل شعبه اعمال شد.')
                return redirect(f'/shifts/today/?mode=weekly&branch={selected_branch.pk}')
        elif action in ('save_employee_weekly','reset_employee_weekly'):
            try: employee_id=int(request.POST.get('employee') or 0)
            except (TypeError,ValueError): employee_id=0
            employee=scoped_users.get(employee_id)
            if not employee:
                messages.error(request,'پرسنل انتخاب‌شده در این شعبه معتبر نیست.')
            elif action=='reset_employee_weekly':
                with transaction.atomic():
                    active_rules=EmployeeWorkSchedule.objects.filter(
                        user=employee,effective_from__lte=day,
                    ).filter(Q(effective_until__isnull=True)|Q(effective_until__gte=day))
                    active_rules.filter(effective_from=day).delete()
                    active_rules.filter(effective_from__lt=day).update(effective_until=day-timedelta(days=1))
                    _attendance_audit(request,'employee_weekly_schedule_reset',summary=f'برنامه شخصی {employee.get_full_name() or employee.username} حذف شد',metadata={'employee_id':employee.pk,'effective_from':day.isoformat()})
                messages.success(request,'برنامه شخصی حذف شد؛ این فرد از برنامه شعبه پیروی می‌کند.')
                return redirect(f'/shifts/today/?mode=weekly&branch={selected_branch.pk}&employee={employee.pk}')
            else:
                plan,errors=parse_weekly_plan('employee')
                if errors:
                    for error in errors: messages.error(request,error)
                else:
                    with transaction.atomic():
                        for values in plan:
                            replace_weekly_rule(EmployeeWorkSchedule,{'user':employee},*values)
                        _attendance_audit(request,'employee_weekly_schedule',summary=f'برنامه هفتگی {employee.get_full_name() or employee.username} تنظیم شد',metadata={'employee_id':employee.pk,'effective_from':day.isoformat()})
                    messages.success(request,'برنامه هفتگی اختصاصی پرسنل از امروز ذخیره شد.')
                    return redirect(f'/shifts/today/?mode=weekly&branch={selected_branch.pk}&employee={employee.pk}')
        else:
            selected_ids=[]
            for raw_id in request.POST.getlist('selected'):
                try: selected_ids.append(int(raw_id))
                except (TypeError,ValueError): continue
            selected_ids=list(dict.fromkeys(selected_ids))
            errors=[]; plans=[]
            for user_id in selected_ids:
                user=scoped_users.get(user_id)
                if not user:
                    errors.append('یکی از پرسنل انتخاب‌شده در محدوده دسترسی شما نیست.')
                    continue
                start_raw=(request.POST.get(f'start_{user_id}') or '').strip()
                end_raw=(request.POST.get(f'end_{user_id}') or '').strip()
                try:
                    start_time=datetime.strptime(start_raw,'%H:%M').time()
                    end_time=datetime.strptime(end_raw,'%H:%M').time()
                except ValueError:
                    errors.append(f'ساعت کاری {user.get_full_name() or user.username} کامل یا معتبر نیست.')
                    continue
                plans.append((user,start_time,end_time))
            if not selected_ids: errors.append('حداقل یک نفر را برای اعمال ساعت کاری انتخاب کنید.')
            if errors:
                for error in errors: messages.error(request,error)
            else:
                with transaction.atomic():
                    for user,start_time,end_time in plans:
                        branch=user.profile.branch
                        shift=WorkShift.objects.filter(
                            branch=branch,start_time=start_time,end_time=end_time,is_active=True,
                        ).order_by('pk').first()
                        if not shift:
                            shift=WorkShift.objects.create(
                                name=f'روزانه {start_time.strftime("%H:%M")} تا {end_time.strftime("%H:%M")}',
                                branch=branch,start_time=start_time,end_time=end_time,
                                grace_minutes=branch.grace_minutes,report_required=True,is_active=True,
                            )
                        ShiftAssignment.objects.update_or_create(
                            user=user,date=day,
                            defaults={'shift':shift,'created_by':request.user,'note':'تنظیم سریع ساعت کاری امروز'},
                        )
                    _attendance_audit(request,'bulk_shift_assignment',summary=f'ساعت کاری امروز برای {len(plans)} نفر تنظیم شد',metadata={'date':day.isoformat(),'employee_ids':[user.pk for user,_,_ in plans]})
                messages.success(request,f'ساعت کاری امروز برای {len(plans)} نفر با موفقیت ذخیره شد.')
                return redirect(f'/shifts/today/?branch={selected_branch.pk}')

    assignments={item.user_id:item for item in ShiftAssignment.objects.select_related('shift').filter(date=day,user_id__in=scoped_users)}
    rows=[]
    source_labels={'personal':'اختصاصی امروز','employee_weekly':'هفتگی شخصی','branch_weekly':'هفتگی شعبه','group':'گروه شیفت','branch':'ساعت شعبه','default':'تعیین نشده'}
    for user in scoped_users.values():
        rule=shift_rule(user,day)
        rows.append({'user':user,'start':rule.get('start'),'end':rule.get('end'),'source':source_labels.get(rule.get('source'),'برنامه پایه'),'is_personal':user.pk in assignments,'is_off':rule.get('is_off',False)})

    active_filter=Q(effective_until__isnull=True)|Q(effective_until__gte=day)
    personal_weekly_user_ids=set(
        EmployeeWorkSchedule.objects.filter(
            user_id__in=scoped_users,effective_from__lte=day,
        ).filter(active_filter).values_list('user_id',flat=True)
    )
    for row in rows:
        row['has_weekly_override']=row['user'].pk in personal_weekly_user_ids
    branch_rules={}
    if selected_branch:
        for rule in BranchWorkSchedule.objects.filter(branch=selected_branch,effective_from__lte=day).filter(active_filter).order_by('weekday','-effective_from','-pk'):
            branch_rules.setdefault(rule.weekday,rule)
    branch_days=[]
    for weekday,label in weekday_order:
        rule=branch_rules.get(weekday)
        branch_days.append({'weekday':weekday,'label':label,'is_working':rule.is_working if rule else True,'start':rule.start_time if rule else getattr(selected_branch,'work_start',None),'end':rule.end_time if rule else getattr(selected_branch,'work_end',None),'configured':bool(rule)})

    employee_id=request.POST.get('employee') or request.GET.get('employee')
    try: employee_id=int(employee_id) if employee_id else None
    except (TypeError,ValueError): employee_id=None
    selected_employee=scoped_users.get(employee_id) if employee_id else (next(iter(scoped_users.values()),None))
    employee_rules={}
    if selected_employee:
        for rule in EmployeeWorkSchedule.objects.filter(user=selected_employee,effective_from__lte=day).filter(active_filter).order_by('weekday','-effective_from','-pk'):
            employee_rules.setdefault(rule.weekday,rule)
    branch_day_map={x['weekday']:x for x in branch_days}
    all_employee_rules={}
    for rule in EmployeeWorkSchedule.objects.filter(
        user_id__in=scoped_users,effective_from__lte=day,
    ).filter(active_filter).order_by('user_id','weekday','-effective_from','-pk'):
        all_employee_rules.setdefault((rule.user_id,rule.weekday),rule)
    for row in rows:
        weekly_days=[]
        for weekday,label in weekday_order:
            personal=all_employee_rules.get((row['user'].pk,weekday))
            inherited=branch_day_map[weekday]
            weekly_days.append({
                'weekday':weekday,
                'label':label,
                'is_working':personal.is_working if personal else inherited['is_working'],
                'start':personal.start_time if personal else inherited['start'],
                'end':personal.end_time if personal else inherited['end'],
                'personal':bool(personal),
            })
        row['weekly_days']=weekly_days
    employee_days=[]
    for weekday,label in weekday_order:
        personal=employee_rules.get(weekday); inherited=branch_day_map[weekday]
        employee_days.append({'weekday':weekday,'label':label,'is_working':personal.is_working if personal else inherited['is_working'],'start':personal.start_time if personal else inherited['start'],'end':personal.end_time if personal else inherited['end'],'personal':bool(personal)})

    return render(request,'core/shift_today_bulk.html',{
        'rows':rows,'today':day,'branches':branches,'selected_branch':selected_branch,
        'weekday_order':weekday_order,'branch_days':branch_days,'employee_days':employee_days,
        'selected_employee':selected_employee,'mode':request.GET.get('mode','today'),
    })

@login_required
def correction_list(request):
    role=role_of(request.user); qs=AttendanceCorrectionRequest.objects.select_related('user','attendance').all()
    if role in PERSONNEL_ROLES: qs=qs.filter(user=request.user)
    elif role=='manager': qs=qs.filter(user__profile__branch=request.user.profile.branch)
    return render(request,'core/correction_list.html',{'items':qs[:100],'can_review':role in MANAGEMENT_ROLES})

@login_required
def correction_create(request):
    form=AttendanceCorrectionForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False); obj.user=request.user
        obj.attendance=Attendance.objects.filter(user=request.user,date=obj.date).first(); obj.save()
        messages.success(request,'درخواست اصلاح حضور ارسال شد.'); return redirect('correction_list')
    return render(request,'core/generic_form.html',{'form':form,'title':'درخواست اصلاح حضور','button':'ارسال درخواست'})

@manager_required
def correction_review(request,pk):
    obj=get_object_or_404(AttendanceCorrectionRequest,pk=pk)
    if role_of(request.user)=='manager' and obj.user.profile.branch_id!=request.user.profile.branch_id: return redirect('correction_list')
    form=AttendanceCorrectionReviewForm(request.POST or None,instance=obj)
    if request.method=='POST' and form.is_valid():
        approve_correction(obj,request.user,form.cleaned_data['status'],form.cleaned_data.get('manager_note',''))
        messages.success(request,'درخواست اصلاح حضور بررسی شد.'); return redirect('correction_list')
    return render(request,'core/generic_form.html',{'form':form,'title':'بررسی اصلاح حضور','button':'ثبت نتیجه'})

@manager_required
def automatic_kpi_dashboard(request):
    end=timezone.localdate(); start=end-timedelta(days=29)
    users=User.objects.filter(profile__is_active=True).select_related('profile','profile__branch')
    if role_of(request.user)=='manager': users=users.filter(profile__branch=request.user.profile.branch)
    elif role_of(request.user)=='internal_manager': users=users.filter(profile__role__in=PERSONNEL_ROLES)
    rows=[]
    for u in users:
        data=auto_kpi(u,start,end); data['user']=u; rows.append(data)
    rows.sort(key=lambda x:x['score'],reverse=True)
    return render(request,'core/automatic_kpi.html',{'rows':rows,'start':start,'end':end})

def management_employee_status_api(request):
    if not _api_manager(request): return JsonResponse({'error':'unauthorized'},status=401)
    uid=request.GET.get('user_id'); name=(request.GET.get('name') or '').strip()
    users=User.objects.filter(profile__is_active=True).select_related('profile','profile__branch')
    if request.user.is_authenticated and role_of(request.user)=='internal_manager':
        users=users.filter(profile__role__in=PERSONNEL_ROLES)
    if uid: users=users.filter(pk=uid)
    elif name: users=users.filter(Q(first_name__icontains=name)|Q(last_name__icontains=name)|Q(username__icontains=name))
    user=users.first()
    if not user: return JsonResponse({'error':'employee not found'},status=404)
    today=timezone.localdate(); rec=Attendance.objects.filter(user=user,date=today).first(); today_rule=shift_rule(user,today)
    missing=missing_report_days(user,days=31,end=today-timedelta(days=1))
    kpi=auto_kpi(user,today-timedelta(days=29),today)
    return JsonResponse({'name':user.get_full_name() or user.username,'branch':user.profile.branch.name if user.profile.branch else None,
        'date':format_jalali(today),'check_in':timezone.localtime(rec.check_in).strftime('%H:%M') if rec and rec.check_in else None,
        'check_out':timezone.localtime(rec.check_out).strftime('%H:%M') if rec and rec.check_out else None,
        'status':rec.status if rec else ('off' if today_rule.get('is_off') else 'missing'),'missing_report_nights_31d':len(missing),'missing_report_dates':[format_jalali(x) for x in missing],
        'auto_kpi_30d':kpi},json_dumps_params={'ensure_ascii':False})


def _branch_scope_for_manager(request):
    branch_id = request.GET.get('branch')
    if role_of(request.user) == 'manager':
        return request.user.profile.branch
    if branch_id:
        from .models import Branch
        return Branch.objects.filter(pk=branch_id, is_active=True).first()
    return None


def _branch_live_payload(branch=None, day=None):
    from .models import Branch, FinancialTransaction
    day = day or timezone.localdate()
    users = User.objects.filter(profile__is_active=True).select_related('profile','profile__branch')
    if branch:
        users = users.filter(profile__branch=branch)
    rows=[]
    counters={'present':0,'late':0,'missing':0,'leave':0}
    for u in users.order_by('profile__branch__name','last_name','first_name','username'):
        leave = LeaveRequest.objects.filter(user=u,status='approved',start_date__lte=day,end_date__gte=day).first()
        rec = Attendance.objects.filter(user=u,date=day).first()
        shift=shift_rule(u,day)
        if leave:
            status='leave'; label=leave.get_request_type_display()
        elif rec and rec.check_in:
            status=attendance_status_for(u,day,rec.check_in)
            label='با تأخیر' if status=='late' else 'حاضر'
        elif shift.get('is_off'):
            status='off'; label='روز غیرکاری'
        else:
            status='missing'; label='ورود ثبت نشده'
        counters[status] = counters.get(status,0)+1
        overdue = Task.objects.filter(assigned_to=u,status__in=('todo','doing'),due_date__lt=day).count()
        missing_reports = len(missing_report_days(u,days=7,end=day-timedelta(days=1)))
        expected_start=shift.get('start')
        late_minutes=0
        if rec and rec.check_in and expected_start:
            expected_dt=timezone.make_aware(datetime.combine(day,expected_start),timezone.get_current_timezone())
            late_minutes=max(0,int((rec.check_in-expected_dt).total_seconds()//60))
        report_today=DailyReport.objects.filter(user=u,created_at__date=day).exists()
        rows.append({
            'id':u.id,
            'name':u.get_full_name() or u.username,
            'branch':u.profile.branch.name if u.profile.branch else '—',
            'job_title':u.profile.job_title,
            'avatar':u.profile.avatar.url if u.profile.avatar else None,
            'status':status,
            'status_label':label,
            'check_in':timezone.localtime(rec.check_in).strftime('%H:%M') if rec and rec.check_in else None,
            'check_out':timezone.localtime(rec.check_out).strftime('%H:%M') if rec and rec.check_out else None,
            'expected_start':expected_start.strftime('%H:%M') if expected_start else None,
            'late_minutes':late_minutes,
            'location_status':rec.check_in_location_status if rec else None,
            'location_distance_m':rec.check_in_distance_m if rec else None,
            'report_today':report_today,
            'is_off':bool(shift.get('is_off')),
            'overdue_tasks':overdue,
            'missing_reports_7d':missing_reports,
        })
    tx = FinancialTransaction.objects.filter(occurred_at__date=day)
    if branch: tx=tx.filter(branch=branch)
    revenue = tx.aggregate(x=Sum('amount'))['x'] or 0
    overdue_tasks = Task.objects.filter(status__in=('todo','doing'),due_date__lt=day,assigned_to__profile__is_active=True)
    if branch: overdue_tasks=overdue_tasks.filter(assigned_to__profile__branch=branch)
    reports_today = DailyReport.objects.filter(created_at__date=day)
    if branch: reports_today=reports_today.filter(user__profile__branch=branch)
    scheduled_rows=[p for p in rows if not p['is_off']]
    total_people=max(1,len(scheduled_rows))
    present_people=counters.get('present',0)+counters.get('late',0)
    attendance_rate=round(present_people*100/total_people)
    ontime_rate=round(counters.get('present',0)*100/total_people)
    missing_reports_today=sum(1 for p in scheduled_rows if not p['report_today'])
    report_rate=round((len(scheduled_rows)-missing_reports_today)*100/total_people)

    # Real task completion metric for today (no decorative/hard-coded KPI).
    tasks_today = Task.objects.filter(
        assigned_to__in=users,
        due_date=day,
        assigned_to__profile__is_active=True,
    )
    if branch:
        tasks_today = tasks_today.filter(assigned_to__profile__branch=branch)
    tasks_today_total = tasks_today.count()
    tasks_today_done = tasks_today.filter(status='done').count()
    task_completion_rate = round(tasks_today_done * 100 / max(1, tasks_today_total)) if tasks_today_total else 100

    # Internal-request data powers the approved owner dashboard. Keep the
    # branch scope aligned with the rest of the management payload so a branch
    # manager never sees another branch's requests.
    internal_requests_qs = InternalRequest.objects.select_related(
        'requester', 'requester__profile', 'assigned_to'
    ).order_by('-created_at')
    if branch:
        internal_requests_qs = internal_requests_qs.filter(requester__profile__branch=branch)
    request_counts = {'open': 0, 'doing': 0, 'done': 0, 'rejected': 0}
    for item in internal_requests_qs.values('status').annotate(n=Count('id')):
        request_counts[item['status']] = item['n']
    request_total = sum(request_counts.values())
    request_open = request_counts['open'] + request_counts['doing']
    request_base = max(1, request_total)
    request_open_end = round(request_counts['open'] * 100 / request_base)
    request_doing_end = request_open_end + round(request_counts['doing'] * 100 / request_base)
    request_done_end = request_doing_end + round(request_counts['done'] * 100 / request_base)

    recent_request_activity = []
    activity_colors = {'open': 'green', 'doing': 'blue', 'done': 'teal', 'rejected': 'red'}
    for item in internal_requests_qs[:5]:
        requester_name = item.requester.get_full_name() or item.requester.username
        profile = getattr(item.requester, 'profile', None)
        recent_request_activity.append({
            'title': item.title,
            'person': requester_name,
            'job_title': getattr(profile, 'job_title', '') or 'پرسنل',
            'avatar': profile.avatar.url if profile and profile.avatar else '',
            'status': item.status,
            'status_label': item.get_status_display(),
            'color': activity_colors.get(item.status, 'green'),
            'time': timezone.localtime(item.updated_at).strftime('%H:%M'),
        })

    # Lightweight 7-day management trend data.
    trend=[]
    request_trend=[]
    for offset in range(6,-1,-1):
        d=day-timedelta(days=offset)
        active_users=users
        daily_records=Attendance.objects.filter(date=d,user__in=active_users)
        present_count=daily_records.filter(check_in__isnull=False).values('user').distinct().count()
        late_count=daily_records.filter(status='late').values('user').distinct().count()
        report_count=DailyReport.objects.filter(created_at__date=d,user__in=active_users).values('user').distinct().count()
        trend.append({
            'label':format_jalali(d)[5:],
            'present':present_count,
            'late':late_count,
            'reports':report_count,
        })
        daily_request_count = internal_requests_qs.filter(created_at__date=d).count()
        request_trend.append({'label': format_jalali(d)[5:], 'count': daily_request_count})

    device_issues = DeviceIssue.objects.filter(reporter__in=users).select_related('reporter','branch').order_by('-created_at')
    if branch:
        device_issues = device_issues.filter(branch=branch)
    device_open = device_issues.exclude(status='resolved')
    device_recent = [{
        'id': x.id, 'device_name': x.device_name, 'description': x.description[:90],
        'status': x.status, 'status_label': x.get_status_display(),
        'reporter': x.reporter.get_full_name() or x.reporter.username,
        'branch': x.branch.name if x.branch else '—',
        'time': timezone.localtime(x.created_at).strftime('%H:%M'),
    } for x in device_issues[:4]]

    rejected_attempts=AuditLog.objects.filter(
        action='attendance_location_rejected',
        created_at__date=day,
    )

    device_issues_qs=DeviceIssue.objects.exclude(status='resolved')
    if branch:
        device_issues_qs=device_issues_qs.filter(branch=branch)
    device_open_count=device_issues_qs.count()
    device_new_count=device_issues_qs.filter(status='new').count()
    device_reviewing_count=device_issues_qs.filter(status='reviewing').count()
    if branch:
        rejected_attempts=rejected_attempts.filter(metadata__branch_id=branch.id)

    return {
        'date':format_jalali(day),
        'branch':branch.name if branch else 'همه شعب',
        'counts':counters,
        'revenue_today':str(revenue),
        'overdue_tasks':overdue_tasks.count(),
        'reports_today':reports_today.values('user').distinct().count(),
        'missing_reports_today':missing_reports_today,
        'unverified_locations':sum(1 for p in rows if p['check_in'] and p['location_status'] not in ('verified','manual')),
        'rejected_location_attempts':rejected_attempts.count(),
        'device_open_count':device_open_count,
        'device_new_count':device_new_count,
        'device_reviewing_count':device_reviewing_count,
        'attendance_rate':attendance_rate,
        'ontime_rate':ontime_rate,
        'report_rate':report_rate,
        'task_completion_rate':task_completion_rate,
        'average_kpi':round((attendance_rate+report_rate+task_completion_rate)/3),
        'tasks_today_total':tasks_today_total,
        'tasks_today_done':tasks_today_done,
        'present_people':present_people,
        'action_required_count':(
            counters.get('late',0) + missing_reports_today
            + overdue_tasks.count() + device_open_count
        ),
        'request_total':request_total,
        'request_open':request_open,
        'request_counts':request_counts,
        'request_open_end':request_open_end,
        'request_doing_end':request_doing_end,
        'request_done_end':request_done_end,
        'request_activity':recent_request_activity,
        'request_trend':request_trend,
        'device_open':device_open.count(),
        'device_recent':device_recent,
        'total_people':len(rows),
        'trend':trend,
        'people':rows,
        'generated_at':timezone.localtime().strftime('%H:%M:%S'),
    }


@manager_required
def branch_live_dashboard(request):
    from .models import Branch
    branch = _branch_scope_for_manager(request)
    branches = Branch.objects.filter(is_active=True).order_by('name')
    if role_of(request.user)=='manager':
        branches=branches.filter(pk=request.user.profile.branch_id)
        branch=request.user.profile.branch
    data=_branch_live_payload(branch)
    if role_of(request.user)=='internal_manager':
        data.pop('revenue_today',None)
    alerts=StaffNotification.objects.filter(user=request.user,is_read=False)[:12]
    announcements=Announcement.objects.filter(is_active=True)
    if branch:
        announcements=announcements.filter(Q(branch__isnull=True)|Q(branch=branch))
    return render(request,'core/branch_live.html',{
        'data':data,
        'branches':branches,
        'selected_branch':branch,
        'alerts':alerts,
        'dashboard_announcements':announcements.order_by('-created_at')[:4],
    })


@manager_required
def branch_live_api(request):
    branch=_branch_scope_for_manager(request)
    data=_branch_live_payload(branch)
    if role_of(request.user)=='internal_manager':
        data.pop('revenue_today',None)
    return JsonResponse(data,json_dumps_params={'ensure_ascii':False})


@manager_required
def smart_alerts_run(request):
    if request.method!='POST':
        return JsonResponse({'error':'POST required'},status=405)
    count=generate_smart_alerts()
    return JsonResponse({'created':count,'message':f'{count} اعلان جدید ساخته شد.'},json_dumps_params={'ensure_ascii':False})


def _employee_access(request, employee):
    if role_of(request.user)=='admin':
        return True
    if role_of(request.user)=='internal_manager':
        return employee.role in PERSONNEL_ROLES
    if role_of(request.user)=='manager':
        return employee.branch_id == getattr(request.user.profile,'branch_id',None)
    return employee.user_id == request.user.id


def _employee_or_redirect(request, pk):
    employee=get_object_or_404(
        EmployeeProfile.objects.select_related('user','branch'),pk=pk
    )
    if not _employee_access(request,employee):
        messages.error(request,'به اطلاعات این پرسنل دسترسی ندارید.')
        return None
    return employee


@manager_required
def employee_reports(request,pk):
    employee=_employee_or_redirect(request,pk)
    if employee is None:
        return redirect('employee_list')
    reports=(DailyReport.objects.select_related('user','branch','user__profile')
             .filter(user=employee.user).order_by('-created_at')[:200])
    return render(request,'core/report_list.html',{
        'reports':reports,
        'filtered_employee':employee,
    })


@manager_required
def employee_attendance(request,pk):
    employee=_employee_or_redirect(request,pk)
    if employee is None:
        return redirect('employee_list')
    try:
        period=int(request.GET.get('days','30'))
    except (TypeError,ValueError):
        period=30
    if period not in (30,60,90):
        period=30
    today=timezone.localdate()
    start=today-timedelta(days=period-1)
    records=list(
        Attendance.objects.filter(user=employee.user,date__range=(start,today))
        .select_related('branch').order_by('-date')
    )
    worked_total=0
    for record in records:
        minutes=record.worked_minutes
        if minutes is not None:
            worked_total+=minutes
            record.worked_label=f'{minutes//60:02d}:{minutes%60:02d}'
        else:
            record.worked_label='—'
    stats={
        'present':sum(1 for r in records if r.check_in),
        'on_time':sum(1 for r in records if r.check_in and r.status=='present'),
        'late':sum(1 for r in records if r.status=='late'),
        'worked':f'{worked_total//60:02d}:{worked_total%60:02d}',
    }
    return render(request,'core/employee_attendance.html',{
        'employee':employee,
        'records':records,
        'stats':stats,
        'period':period,
        'start':start,
        'today':today,
    })


@manager_required
def employee_task_create(request,pk):
    employee=_employee_or_redirect(request,pk)
    if employee is None:
        return redirect('employee_list')
    form=TaskForm(request.POST or None)
    form.fields.pop('assigned_to',None)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False)
        obj.assigned_to=employee.user
        obj.created_by=request.user
        obj.save()
        messages.success(request,f'وظیفه جدید برای {employee.user.get_full_name() or employee.user.username} ثبت شد.')
        return redirect('employee_file',pk=employee.pk)
    return render(request,'core/employee_management_form.html',{
        'form':form,
        'employee':employee,
        'title':'وظیفه جدید',
        'subtitle':'وظیفه مستقیماً برای همین پرسنل ثبت می‌شود.',
        'button':'ثبت وظیفه',
        'form_kind':'task',
    })


@manager_required
def employee_file(request,pk):
    employee=get_object_or_404(EmployeeProfile.objects.select_related('user','branch'),pk=pk)
    if not _employee_access(request,employee):
        messages.error(request,'به این پرونده دسترسی ندارید.')
        return redirect('employee_list')
    user=employee.user
    today=timezone.localdate()
    start=today-timedelta(days=29)
    attendance=Attendance.objects.filter(user=user,date__range=(start,today)).order_by('-date')
    leaves=LeaveRequest.objects.filter(user=user).order_by('-created_at')[:20]
    tasks=Task.objects.filter(assigned_to=user).order_by('status','due_date')[:30]
    reports=DailyReport.objects.filter(user=user).order_by('-created_at')[:20]
    scores=ScoreEvent.objects.filter(user=user).order_by('-event_date','-created_at')[:30]
    actions=PersonnelAction.objects.filter(user=user).order_by('-event_date','-created_at')
    kpi=auto_kpi(user,start,today)
    documents=employee.documents.all()
    stats={
        'attendance_days':attendance.filter(check_in__isnull=False).count(),
        'late_days':attendance.filter(status='late').count(),
        'reports':DailyReport.objects.filter(user=user,created_at__date__range=(start,today)).count(),
        'task_done':Task.objects.filter(assigned_to=user,status='done',updated_at__date__range=(start,today)).count(),
        'task_open':Task.objects.filter(assigned_to=user,status__in=('todo','doing')).count(),
        'documents':documents.count(),
        'actions':actions.count(),
    }
    return render(request,'core/employee_file.html',{
        'employee':employee,'attendance':attendance[:15],'leaves':leaves,'tasks':tasks,
        'reports':reports,'scores':scores,'actions':actions[:12],'documents':documents,'kpi':kpi,'stats':stats,
        'start':start,'today':today
    })


@manager_required
def employee_document_add(request,pk):
    employee=get_object_or_404(EmployeeProfile.objects.select_related('user','branch'),pk=pk)
    if not _employee_access(request,employee):
        messages.error(request,'به این پرسنل دسترسی ندارید.')
        return redirect('employee_list')
    form=EmployeeDocumentForm(request.POST or None,request.FILES or None)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False)
        obj.employee=employee
        obj.uploaded_by=request.user
        obj.save()
        messages.success(request,'مدرک به پرونده پرسنلی اضافه شد.')
        return redirect('employee_file',pk=pk)
    return render(request,'core/generic_form.html',{'form':form,'title':f'افزودن مدرک برای {employee.user.get_full_name() or employee.user.username}','button':'ذخیره مدرک'})


def _checklist_templates_for(user):
    p=user.profile
    return ChecklistTemplate.objects.filter(is_active=True).filter(
        Q(branch__isnull=True)|Q(branch=p.branch)
    ).filter(
        Q(role='')|Q(role=p.role)
    ).filter(
        Q(job_title='')|Q(job_title=p.job_title)
    ).prefetch_related('items').order_by('name').distinct()


@login_required
def checklist_today(request):
    day=timezone.localdate()
    templates=_checklist_templates_for(request.user)
    completions={
        x.item_id:x for x in ChecklistCompletion.objects.filter(user=request.user,date=day).select_related('item')
    }
    rows=[]
    total=done=0
    for template in templates:
        item_rows=[]
        for item in template.items.all():
            comp=completions.get(item.id)
            total+=1
            if comp and comp.is_done: done+=1
            item_rows.append({'item':item,'completion':comp,'done':bool(comp and comp.is_done)})
        rows.append({'template':template,'items':item_rows})
    progress=round(done*100/total) if total else 100
    return render(request,'core/checklist_today.html',{'rows':rows,'day':day,'total':total,'done':done,'progress':progress})


@login_required
def checklist_toggle(request,item_id):
    if request.method!='POST':
        return redirect('checklist_today')
    item=get_object_or_404(ChecklistItem.objects.select_related('template'),pk=item_id,template__is_active=True)
    allowed_ids={i.id for t in _checklist_templates_for(request.user) for i in t.items.all()}
    if item.id not in allowed_ids:
        messages.error(request,'این مورد برای شما تعریف نشده است.')
        return redirect('checklist_today')
    day=timezone.localdate()
    obj,_=ChecklistCompletion.objects.get_or_create(user=request.user,item=item,date=day)
    obj.is_done=not obj.is_done
    obj.completed_at=timezone.now() if obj.is_done else None
    obj.note=request.POST.get('note','')[:250]
    obj.save()
    return redirect('checklist_today')


@manager_required
def checklist_templates(request):
    qs=ChecklistTemplate.objects.select_related('branch','created_by').prefetch_related('items').order_by('branch__name','name')
    if role_of(request.user)=='manager':
        qs=qs.filter(Q(branch=request.user.profile.branch)|Q(branch__isnull=True))
    return render(request,'core/checklist_templates.html',{'templates':qs})


@manager_required
def checklist_template_create(request):
    form=ChecklistTemplateForm(request.POST or None)
    if role_of(request.user)=='manager':
        form.fields['branch'].queryset=form.fields['branch'].queryset.filter(pk=request.user.profile.branch_id)
        form.fields['branch'].initial=request.user.profile.branch
        form.fields['role'].choices=[('employee','کارمند'),('manager','مدیر شعبه')]
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False); obj.created_by=request.user
        if role_of(request.user)=='manager': obj.branch=request.user.profile.branch
        obj.save()
        messages.success(request,'چک‌لیست ساخته شد؛ حالا موارد آن را اضافه کنید.')
        return redirect('checklist_template_detail',pk=obj.pk)
    return render(request,'core/generic_form.html',{'form':form,'title':'ساخت چک‌لیست روزانه','button':'ساخت'})


@manager_required
def checklist_template_detail(request,pk):
    template=get_object_or_404(ChecklistTemplate.objects.select_related('branch'),pk=pk)
    if role_of(request.user)=='manager' and template.branch_id not in (None,request.user.profile.branch_id):
        messages.error(request,'دسترسی مجاز نیست.')
        return redirect('checklist_templates')
    form=ChecklistItemForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        item=form.save(commit=False); item.template=template; item.save()
        messages.success(request,'مورد جدید اضافه شد.')
        return redirect('checklist_template_detail',pk=pk)
    return render(request,'core/checklist_template_detail.html',{'template':template,'form':form})


@manager_required
def checklist_team_status(request):
    day=timezone.localdate()
    try:
        if request.GET.get('date'): day=parse_jalali(request.GET['date'])
    except Exception:
        pass
    users=User.objects.filter(profile__is_active=True).select_related('profile','profile__branch')
    if role_of(request.user)=='manager':
        users=users.filter(profile__branch=request.user.profile.branch)
    rows=[]
    for user in users.order_by('profile__branch__name','last_name','first_name','username'):
        templates=_checklist_templates_for(user)
        item_ids=[i.id for t in templates for i in t.items.all()]
        total=len(item_ids)
        done=ChecklistCompletion.objects.filter(user=user,date=day,item_id__in=item_ids,is_done=True).count() if item_ids else 0
        required_ids=[i.id for t in templates for i in t.items.all() if i.is_required]
        required_done=ChecklistCompletion.objects.filter(user=user,date=day,item_id__in=required_ids,is_done=True).count() if required_ids else 0
        rows.append({
            'user':user,'total':total,'done':done,
            'required_total':len(required_ids),'required_done':required_done,
            'percent':round(done*100/total) if total else 100,
        })
    return render(request,'core/checklist_team.html',{'rows':rows,'day':day})


@finance_required
def executive_today(request):
    from .models import Branch, FinancialTransaction
    day=timezone.localdate()
    branch=_branch_scope_for_manager(request)
    users=User.objects.filter(profile__is_active=True).select_related('profile','profile__branch')
    if branch:
        users=users.filter(profile__branch=branch)

    late_people=[]
    missing_people=[]
    leave_people=[]
    checklist_issues=[]
    kpi_issues=[]
    report_issues=[]

    for u in users.order_by('profile__branch__name','last_name','first_name','username'):
        p=u.profile
        leave=LeaveRequest.objects.filter(user=u,status='approved',start_date__lte=day,end_date__gte=day).first()
        rec=Attendance.objects.filter(user=u,date=day).first()
        work_rule=shift_rule(u,day)
        avatar=p.avatar.url if p.avatar else None
        base={'id':u.id,'profile_id':p.id,'name':u.get_full_name() or u.username,'branch':p.branch.name if p.branch else '—','job_title':p.job_title,'avatar':avatar}

        if leave:
            leave_people.append({**base,'label':leave.get_request_type_display()})
        elif rec and rec.check_in:
            status=attendance_status_for(u,day,rec.check_in)
            if status=='late':
                late_people.append({**base,'time':timezone.localtime(rec.check_in).strftime('%H:%M')})
        elif not work_rule.get('is_off'):
            missing_people.append(base)

        # checklist status
        templates=_checklist_templates_for(u)
        items=[i for t in templates for i in t.items.all()]
        required=[i for i in items if i.is_required]
        if required and not work_rule.get('is_off'):
            done_ids=set(ChecklistCompletion.objects.filter(user=u,date=day,is_done=True,item__in=required).values_list('item_id',flat=True))
            missing_required=[i for i in required if i.id not in done_ids]
            if missing_required:
                checklist_issues.append({**base,'missing':len(missing_required),'total':len(required)})

        # KPI issue
        kpi=auto_kpi(u,day-timedelta(days=29),day)
        if kpi['score']<70:
            kpi_issues.append({**base,'score':kpi['score']})

        # missed nightly reports in last 7 completed days
        missed=missing_report_days(u,days=7,end=day-timedelta(days=1))
        if missed:
            report_issues.append({**base,'count':len(missed)})

    overdue_qs=Task.objects.filter(status__in=('todo','doing'),due_date__lt=day).select_related('assigned_to','assigned_to__profile','assigned_to__profile__branch')
    if branch:
        overdue_qs=overdue_qs.filter(assigned_to__profile__branch=branch)
    overdue_tasks=list(overdue_qs.order_by('due_date')[:12])

    tx=FinancialTransaction.objects.filter(occurred_at__date=day)
    if branch: tx=tx.filter(branch=branch)
    revenue_today=tx.aggregate(x=Sum('amount'))['x'] or 0

    yesterday=day-timedelta(days=1)
    tx_y=FinancialTransaction.objects.filter(occurred_at__date=yesterday)
    if branch: tx_y=tx_y.filter(branch=branch)
    revenue_yesterday=tx_y.aggregate(x=Sum('amount'))['x'] or 0
    revenue_change=None
    if revenue_yesterday:
        revenue_change=round((float(revenue_today)-float(revenue_yesterday))*100/float(revenue_yesterday),1)

    branches=Branch.objects.filter(is_active=True).order_by('name')
    if role_of(request.user)=='manager':
        branches=branches.filter(pk=request.user.profile.branch_id)

    branch_cards=[]
    branch_scope=branches if role_of(request.user)=='admin' else branches
    for b in branch_scope:
        bu=User.objects.filter(profile__is_active=True,profile__branch=b)
        present=Attendance.objects.filter(user__in=bu,date=day,check_in__isnull=False).count()
        late=Attendance.objects.filter(user__in=bu,date=day,status='late').count()
        total=bu.count()
        btx=FinancialTransaction.objects.filter(branch=b,occurred_at__date=day).aggregate(x=Sum('amount'))['x'] or 0
        branch_cards.append({'branch':b,'present':present,'late':late,'total':total,'revenue':btx})

    risk_count=len(late_people)+len(missing_people)+len(checklist_issues)+len(kpi_issues)+overdue_qs.count()

    return render(request,'core/executive_today.html',{
        'day':day,'selected_branch':branch,'branches':branches,
        'late_people':late_people,'missing_people':missing_people,'leave_people':leave_people,
        'checklist_issues':checklist_issues,'kpi_issues':kpi_issues,'report_issues':report_issues,
        'overdue_tasks':overdue_tasks,'revenue_today':revenue_today,'revenue_yesterday':revenue_yesterday,
        'revenue_change':revenue_change,'branch_cards':branch_cards,'risk_count':risk_count,
        'team_count':users.count(),
    })


def morning_brief_data(user, branch=None):
    day=timezone.localdate()
    users=User.objects.filter(profile__is_active=True).select_related('profile','profile__branch')
    if branch: users=users.filter(profile__branch=branch)
    late=[]; missing=[]; low_kpi=[]
    for u in users:
        leave=LeaveRequest.objects.filter(user=u,status='approved',start_date__lte=day,end_date__gte=day).exists()
        if leave: continue
        rec=Attendance.objects.filter(user=u,date=day).first()
        work_rule=shift_rule(u,day)
        if rec and rec.check_in and attendance_status_for(u,day,rec.check_in)=='late':
            late.append(u)
        elif (not rec or not rec.check_in) and not work_rule.get('is_off'): missing.append(u)
        k=auto_kpi(u,day-timedelta(days=29),day)
        if k['score']<70: low_kpi.append((u,k['score']))
    overdue=Task.objects.filter(status__in=('todo','doing'),due_date__lt=day)
    if branch: overdue=overdue.filter(assigned_to__profile__branch=branch)
    from .models import FinancialTransaction
    revenue=FinancialTransaction.objects.filter(occurred_at__date=day)
    if branch: revenue=revenue.filter(branch=branch)
    revenue=revenue.aggregate(x=Sum('amount'))['x'] or 0
    return {'day':day,'team':users.count(),'late':late,'missing':missing,'low_kpi':low_kpi,'overdue':overdue.count(),'revenue':revenue}

@finance_required
def morning_brief(request):
    branch=_branch_scope_for_manager(request)
    return render(request,'core/morning_brief.html',{'brief':morning_brief_data(request.user,branch)})

@manager_required
def employee_360(request,pk):
    employee=get_object_or_404(
        EmployeeProfile.objects.select_related('user','branch','shift_group'),
        pk=pk
    )
    if not _employee_access(request,employee):
        messages.error(request,'دسترسی مجاز نیست.')
        return redirect('employee_list')

    u=employee.user
    day=timezone.localdate()
    start30=day-timedelta(days=29)
    start90=day-timedelta(days=89)

    attendance_qs=Attendance.objects.filter(user=u,date__gte=start30).order_by('-date')
    attendance_total=attendance_qs.count()
    attendance_present=attendance_qs.filter(check_in__isnull=False).count()
    late_count=attendance_qs.filter(status='late').count()
    missing_count=max(0,30-attendance_present)
    attendance_rate=round(attendance_present*100/max(1,attendance_total)) if attendance_total else 0

    reports30=DailyReport.objects.filter(user=u,created_at__date__gte=start30,created_at__date__lte=day)
    report_count=reports30.values('created_at__date').distinct().count()

    tasks=Task.objects.filter(assigned_to=u)
    task_total=tasks.count()
    task_done=tasks.filter(status='done').count()
    task_overdue=tasks.filter(status__in=('todo','doing'),due_date__lt=day).count()
    task_rate=round(task_done*100/max(1,task_total)) if task_total else 100

    leaves=LeaveRequest.objects.filter(user=u).order_by('-created_at')[:8]
    corrections=AttendanceCorrectionRequest.objects.filter(user=u).order_by('-created_at')[:8]
    device_issues=DeviceIssue.objects.filter(reporter=u).order_by('-created_at')[:8]
    report_items=DailyReport.objects.filter(user=u).order_by('-created_at')[:8]
    documents=EmployeeDocument.objects.filter(employee=employee).order_by('-created_at')[:8]
    guideline_ack_count=GuidelineAcknowledgement.objects.filter(user=u).count()
    guideline_total=_guidelines_for_user(u).count()

    score30=ScoreEvent.objects.filter(user=u,event_date__gte=start30,event_date__lte=day)
    score_total=score30.aggregate(x=Sum('points'))['x'] or 0

    events=[]
    for a in Attendance.objects.filter(user=u,date__gte=start90):
        if a.check_in:
            label='تأخیر' if a.status=='late' else 'حضور'
            text=timezone.localtime(a.check_in).strftime('%H:%M')
            events.append({'date':a.date,'type':a.status,'title':label,'text':text,'icon':'◷'})
    for x in PersonnelAction.objects.filter(user=u,event_date__gte=start90):
        events.append({'date':x.event_date,'type':x.action_type,'title':x.get_action_type_display(),'text':x.title,'icon':'⚑'})
    for x in ScoreEvent.objects.filter(user=u,event_date__gte=start90):
        events.append({'date':x.event_date,'type':'score','title':'امتیاز','text':f'{x.points:+d} · {x.description}','icon':'★'})
    for x in DeviceIssue.objects.filter(reporter=u,created_at__date__gte=start90):
        events.append({'date':timezone.localdate(x.created_at),'type':'device','title':'گزارش خرابی دستگاه','text':x.device_name,'icon':'⚒'})
    for x in DailyReport.objects.filter(user=u,created_at__date__gte=start90):
        events.append({'date':timezone.localdate(x.created_at),'type':'report','title':'گزارش روزانه','text':normalize_ai_text(x.ai_summary or x.text or x.transcript)[:100],'icon':'▤'})
    events=sorted(events,key=lambda x:x['date'],reverse=True)[:60]

    goals=PerformanceGoal.objects.filter(employee=u,is_active=True)
    kpi=auto_kpi(u,start30,day)
    today_shift=shift_rule(u,day)

    summary={
        'attendance_rate':attendance_rate,
        'late_count':late_count,
        'report_count':report_count,
        'task_rate':task_rate,
        'task_overdue':task_overdue,
        'score_total':score_total,
        'guideline_ack_count':guideline_ack_count,
        'guideline_total':guideline_total,
    }

    return render(request,'core/employee_360.html',{
        'employee':employee,
        'events':events,
        'goals':goals,
        'kpi':kpi,
        'summary':summary,
        'today_shift':today_shift,
        'attendance_recent':attendance_qs[:10],
        'reports_recent':report_items,
        'leaves':leaves,
        'corrections':corrections,
        'device_issues':device_issues,
        'documents':documents,
    })

@manager_required
def personnel_action_add(request,pk):
    employee=_employee_or_redirect(request,pk)
    if employee is None:
        return redirect('employee_list')
    form=PersonnelActionForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.user=employee.user; x.created_by=request.user; x.save()
        StaffNotification.objects.create(user=employee.user,title=x.get_action_type_display(),message=x.title,notification_type='personnel_action',related_date=x.event_date)
        messages.success(request,f'اقدام مدیریتی برای {employee.user.get_full_name() or employee.user.username} ثبت شد.')
        return redirect('employee_360',pk=pk)
    return render(request,'core/employee_management_form.html',{
        'form':form,
        'employee':employee,
        'title':'اقدام مدیریتی',
        'subtitle':'تشویق، تذکر، اخطار یا یادداشت مدیریتی را با شرح روشن ثبت کنید.',
        'button':'ثبت اقدام',
        'form_kind':'management',
    })

@login_required
def personnel_action_ack(request,pk):
    x=get_object_or_404(PersonnelAction,pk=pk,user=request.user)
    if request.method=='POST' and not x.acknowledged_at:
        x.acknowledged_at=timezone.now(); x.save(update_fields=['acknowledged_at'])
    return redirect('profile')

@manager_required
def goals(request):
    qs=PerformanceGoal.objects.select_related('employee','branch')
    if role_of(request.user)=='manager': qs=qs.filter(Q(branch=request.user.profile.branch)|Q(employee__profile__branch=request.user.profile.branch))
    return render(request,'core/goals.html',{'goals':qs})

@manager_required
def goal_add(request):
    form=PerformanceGoalForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.created_by=request.user; x.save(); return redirect('goals')
    return render(request,'core/generic_form.html',{'form':form,'title':'هدف جدید','button':'ثبت هدف'})

@login_required
def internal_requests(request):
    qs=InternalRequest.objects.select_related('requester','assigned_to')
    if role_of(request.user) in PERSONNEL_ROLES: qs=qs.filter(requester=request.user)
    elif role_of(request.user)=='manager': qs=qs.filter(Q(requester__profile__branch=request.user.profile.branch)|Q(assigned_to=request.user))
    return render(request,'core/internal_requests.html',{'requests':qs[:100]})

@login_required
def internal_request_add(request):
    form=InternalRequestForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.requester=request.user; x.save(); return redirect('internal_requests')
    return render(request,'core/generic_form.html',{'form':form,'title':'درخواست داخلی جدید','button':'ارسال درخواست'})

@manager_required
def command_center(request):
    q=(request.GET.get('q') or '').strip()
    answer=None; data=None
    if q:
        qn=q.replace('ي','ی').replace('ك','ک')
        branch=_branch_scope_for_manager(request)
        data=morning_brief_data(request.user,branch)
        if 'مشکل' in qn or 'امروز' in qn:
            answer=f"امروز {len(data['late'])} تأخیر، {len(data['missing'])} ورود ثبت‌نشده، {data['overdue']} Task عقب‌افتاده و {len(data['low_kpi'])} KPI زیر ۷۰ داریم."
        elif 'دیر' in qn or 'تاخیر' in qn or 'تأخیر' in qn:
            answer='، '.join([u.get_full_name() or u.username for u in data['late']]) or 'امروز تأخیری ثبت نشده است.'
        elif 'درآمد' in qn or 'فروش' in qn or 'مالی' in qn:
            if role_of(request.user)=='internal_manager':
                answer='دسترسی بخش مالی برای نقش مدیر داخلی فعال نیست.'
            else:
                answer=f"درآمد ثبت‌شده امروز {data['revenue']} است."
        elif 'kpi' in qn.lower() or 'عملکرد' in qn:
            answer='؛ '.join([f"{u.get_full_name() or u.username}: {s}" for u,s in data['low_kpi']]) or 'KPI زیر ۷۰ دیده نمی‌شود.'
        else:
            answer='می‌توانی درباره مشکلات امروز، تأخیرها، KPI یا Taskهای عقب‌افتاده سؤال کنی.' if role_of(request.user)=='internal_manager' else 'می‌توانی درباره مشکلات امروز، تأخیرها، درآمد، KPI یا Taskهای عقب‌افتاده سؤال کنی.'
    return render(request,'core/command_center.html',{'q':q,'answer':answer,'data':data})


@finance_required
def ceo_score_view(request):
    branch=_branch_scope_for_manager(request)
    data=ceo_score(branch)
    trends=trend_alerts(branch)
    history=CEOScoreSnapshot.objects.filter(branch=branch).order_by('-date')[:30]
    history=list(reversed(list(history)))
    return render(request,'core/ceo_score.html',{'score':data,'trends':trends,'history':history,'selected_branch':branch})

@finance_required
def trend_dashboard(request):
    branch=_branch_scope_for_manager(request)
    return render(request,'core/trends.html',{'trends':trend_alerts(branch),'selected_branch':branch})

@manager_required
def management_calendar(request):
    from .jalali import gregorian_to_jalali, jalali_to_gregorian
    from datetime import date
    branch=_branch_scope_for_manager(request)
    today=timezone.localdate()
    jy,jm,_=gregorian_to_jalali(today.year,today.month,today.day)
    try:
        jy=int(request.GET.get('year') or jy); jm=int(request.GET.get('month') or jm)
    except Exception:
        pass
    data=calendar_events(branch,jy,jm)
    first=data['start']
    # Saturday-first calendar: Python weekday Monday=0; Saturday -> 0
    offset=(first.weekday()+2)%7
    days=[]
    for _ in range(offset): days.append(None)
    event_map={}
    for e in data['events']: event_map.setdefault(e['date'],[]).append(e)
    d=data['start']
    while d<=data['end']:
        _,_,jd=gregorian_to_jalali(d.year,d.month,d.day)
        days.append({'date':d,'jd':jd,'events':event_map.get(d,[]),'today':d==today})
        d+=timedelta(days=1)
    while len(days)%7: days.append(None)
    prev_y,prev_m=(jy-1,12) if jm==1 else (jy,jm-1)
    next_y,next_m=(jy+1,1) if jm==12 else (jy,jm+1)
    return render(request,'core/management_calendar.html',{'days':days,'jy':jy,'jm':jm,'prev_y':prev_y,'prev_m':prev_m,'next_y':next_y,'next_m':next_m,'selected_branch':branch})

@manager_required
def management_event_add(request):
    form=ManagementEventForm(request.POST or None)
    if role_of(request.user)=='manager':
        form.fields['branch'].queryset=form.fields['branch'].queryset.filter(pk=request.user.profile.branch_id)
        form.fields['branch'].initial=request.user.profile.branch
    if request.method=='POST' and form.is_valid():
        x=form.save(commit=False); x.created_by=request.user
        if role_of(request.user)=='manager': x.branch=request.user.profile.branch
        x.save()
        messages.success(request,'رویداد مدیریتی ثبت شد.')
        return redirect('management_calendar')
    return render(request,'core/generic_form.html',{'form':form,'title':'رویداد تقویم مدیریتی','button':'ثبت رویداد'})

@standard_manager_required
def audit_log_view(request):
    qs=AuditLog.objects.select_related('actor')
    if role_of(request.user)=='manager':
        # Managers see audit entries from users in their own branch plus themselves.
        branch=request.user.profile.branch
        qs=qs.filter(Q(actor=request.user)|Q(actor__profile__branch=branch))
    actor=request.GET.get('actor')
    action=request.GET.get('action')
    if actor: qs=qs.filter(actor_id=actor)
    if action: qs=qs.filter(action=action)
    return render(request,'core/audit_log.html',{'logs':qs[:300]})

@finance_required
def ceo_score_api(request):
    branch=_branch_scope_for_manager(request)
    return JsonResponse({'score':ceo_score(branch),'trends':trend_alerts(branch)},json_dumps_params={'ensure_ascii':False})


def _guidelines_for_user(user):
    profile=getattr(user,'profile',None)
    qs=Guideline.objects.filter(is_active=True)
    if not profile:
        return qs.filter(audience='all')
    return qs.filter(
        Q(audience='all') |
        Q(audience='branch',branch=profile.branch) |
        Q(audience='job',job_title=profile.job_title)
    ).distinct().order_by('-published_at')

def _job_duties_for_user(user):
    profile=getattr(user,'profile',None)
    if not profile: return JobDutyTemplate.objects.none()
    qs=JobDutyTemplate.objects.filter(is_active=True)
    return qs.filter(
        (Q(branch__isnull=True)|Q(branch=profile.branch)) &
        (Q(job_title='')|Q(job_title=profile.job_title))
    ).order_by('title')

@login_required
def my_guidelines(request):
    guidelines=_guidelines_for_user(request.user)
    ack_ids=set(GuidelineAcknowledgement.objects.filter(user=request.user,guideline__in=guidelines).values_list('guideline_id',flat=True))
    duties=_job_duties_for_user(request.user)
    return render(request,'core/my_guidelines.html',{'guidelines':guidelines,'ack_ids':ack_ids,'duties':duties})

@login_required
def guideline_ack(request,pk):
    if request.method!='POST': return redirect('my_guidelines')
    guideline=get_object_or_404(_guidelines_for_user(request.user),pk=pk)
    GuidelineAcknowledgement.objects.get_or_create(guideline=guideline,user=request.user)
    messages.success(request,'مطالعه دستورالعمل ثبت شد.')
    return redirect('my_guidelines')

@manager_required
def guidelines_manage(request):
    profile=getattr(request.user,'profile',None)
    guidelines=Guideline.objects.all().order_by('-published_at')
    duties=JobDutyTemplate.objects.all().order_by('title')
    if role_of(request.user)=='manager':
        guidelines=guidelines.filter(Q(branch=profile.branch)|Q(branch__isnull=True))
        duties=duties.filter(Q(branch=profile.branch)|Q(branch__isnull=True))
    return render(request,'core/guidelines_manage.html',{'guidelines':guidelines,'duties':duties})

@manager_required
def guideline_create(request):
    form=GuidelineForm(request.POST or None)
    if role_of(request.user)=='manager':
        form.fields['branch'].queryset=form.fields['branch'].queryset.filter(pk=request.user.profile.branch_id)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False); obj.created_by=request.user
        if role_of(request.user)=='manager' and not obj.branch: obj.branch=request.user.profile.branch
        obj.save(); messages.success(request,'دستورالعمل منتشر شد.'); return redirect('guidelines_manage')
    return render(request,'core/generic_form.html',{'form':form,'title':'دستورالعمل جدید','button':'انتشار'})

@manager_required
def job_duty_create(request):
    form=JobDutyTemplateForm(request.POST or None)
    if role_of(request.user)=='manager':
        form.fields['branch'].queryset=form.fields['branch'].queryset.filter(pk=request.user.profile.branch_id)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False); obj.created_by=request.user
        if role_of(request.user)=='manager' and not obj.branch: obj.branch=request.user.profile.branch
        obj.save(); messages.success(request,'شرح وظایف ثبت شد.'); return redirect('guidelines_manage')
    return render(request,'core/generic_form.html',{'form':form,'title':'شرح وظایف جدید','button':'ذخیره'})


DEVICE_ISSUE_RECIPIENT_USERNAMES=('admin','manager1','sadeghi')

def _device_issue_recipients(issue):
    qs=User.objects.filter(is_active=True).filter(
        Q(username__in=DEVICE_ISSUE_RECIPIENT_USERNAMES) |
        Q(profile__role='admin') |
        Q(profile__role='internal_manager') |
        Q(profile__role='manager',profile__branch=issue.branch)
    ).distinct()
    return qs

def _can_manage_device_issues(user):
    return role_of(user) in MANAGEMENT_ROLES or user.username.lower()=='sadeghi'

@login_required
def device_issue_create(request):
    form=DeviceIssueForm(request.POST or None)
    if request.method=='POST' and form.is_valid():
        issue=form.save(commit=False)
        issue.reporter=request.user
        issue.branch=getattr(getattr(request.user,'profile',None),'branch',None)
        issue.save()
        title=f'خرابی دستگاه: {issue.device_name}'
        reporter_name=request.user.get_full_name() or request.user.username
        for recipient in _device_issue_recipients(issue):
            StaffNotification.objects.create(
                user=recipient,
                title=title,
                message=f'{reporter_name} خرابی دستگاه «{issue.device_name}» را گزارش کرده است. لطفاً بررسی شود.',
                notification_type='device_issue',
                related_date=timezone.localdate(),
            )
        messages.success(request,'گزارش خرابی ثبت شد و برای مسئولان مربوطه ارسال شد.')
        return redirect('device_issue_mine')
    return render(request,'core/device_issue_form.html',{'form':form})

@login_required
def device_issue_mine(request):
    issues=DeviceIssue.objects.filter(reporter=request.user).select_related('branch','resolved_by')
    return render(request,'core/device_issue_mine.html',{'issues':issues})

@login_required
def device_issue_manage(request):
    if not _can_manage_device_issues(request.user):
        messages.error(request,'دسترسی مجاز نیست.')
        return redirect('dashboard')
    issues=DeviceIssue.objects.select_related('reporter','reporter__profile','branch','resolved_by')
    if role_of(request.user)=='manager':
        issues=issues.filter(branch=request.user.profile.branch)
    status=request.GET.get('status')
    if status in ('new','reviewing','resolved'):
        issues=issues.filter(status=status)
    return render(request,'core/device_issue_manage.html',{'issues':issues,'selected_status':status or ''})

@login_required
def device_issue_review(request,pk):
    if not _can_manage_device_issues(request.user):
        messages.error(request,'دسترسی مجاز نیست.')
        return redirect('dashboard')
    issue=get_object_or_404(DeviceIssue,pk=pk)
    if role_of(request.user)=='manager' and issue.branch_id!=request.user.profile.branch_id:
        messages.error(request,'دسترسی مجاز نیست.')
        return redirect('device_issue_manage')
    old_status=issue.status
    form=DeviceIssueReviewForm(request.POST or None,instance=issue)
    if request.method=='POST' and form.is_valid():
        obj=form.save(commit=False)
        if obj.status=='resolved' and old_status!='resolved':
            obj.resolved_at=timezone.now()
            obj.resolved_by=request.user
        elif obj.status!='resolved':
            obj.resolved_at=None
            obj.resolved_by=None
        obj.save()
        if obj.reporter_id:
            StaffNotification.objects.create(
                user=obj.reporter,
                title=f'پیگیری خرابی: {obj.device_name}',
                message=f'وضعیت گزارش خرابی شما به «{obj.get_status_display()}» تغییر کرد.'
                        + (f' توضیح: {obj.manager_note}' if obj.manager_note else ''),
                notification_type='device_issue',
                related_date=timezone.localdate(),
            )
        messages.success(request,'وضعیت خرابی بروزرسانی شد.')
        return redirect('device_issue_manage')
    return render(request,'core/device_issue_review.html',{'form':form,'issue':issue})


@manager_required
def action_center(request):
    role=role_of(request.user)
    profile=getattr(request.user,'profile',None)
    day=timezone.localdate()

    # Operational alerts belong to employee accounts. Manager/admin accounts
    # must not appear as absent or missing-report staff in their own queue.
    users=User.objects.filter(
        profile__is_active=True,
        profile__role__in=PERSONNEL_ROLES,
    ).select_related('profile','profile__branch')
    if role=='manager':
        users=users.filter(profile__branch=getattr(profile,'branch',None))
    user_ids=list(users.values_list('id',flat=True))

    items=[]

    def add_item(kind,priority,title,subtitle,user=None,url='#',created_at=None,icon='•',meta=None):
        rank={'critical':0,'high':1,'medium':2,'low':3}.get(priority,4)
        dt=created_at or timezone.now()
        if not hasattr(dt,'timestamp'):
            dt=timezone.now()
        items.append({
            'kind':kind,'priority':priority,'rank':rank,
            'title':title,'subtitle':subtitle,'user':user,
            'url':url,'created_at':dt,'icon':icon,'meta':meta or {},
        })

    # Pending leave requests
    for x in LeaveRequest.objects.filter(user_id__in=user_ids,status='pending').select_related('user','user__profile','user__profile__branch'):
        add_item(
            'leave','medium','درخواست مرخصی/ماموریت',
            f'{x.get_request_type_display()} · {format_jalali(x.start_date)} تا {format_jalali(x.end_date)}',
            x.user,f'/requests/{x.pk}/review/',x.created_at,'◫'
        )

    # Pending attendance corrections
    for x in AttendanceCorrectionRequest.objects.filter(user_id__in=user_ids,status='pending').select_related('user','user__profile'):
        add_item(
            'correction','high','درخواست اصلاح حضور',
            f'{format_jalali(x.date)} · {(x.reason or "")[:90]}',
            x.user,f'/attendance/corrections/{x.pk}/review/',x.created_at,'◷'
        )

    # Open device issues
    for x in DeviceIssue.objects.filter(reporter_id__in=user_ids).exclude(status='resolved').select_related('reporter','branch'):
        add_item(
            'device','high' if x.status=='new' else 'medium',
            f'خرابی دستگاه: {x.device_name}',
            (x.description or '')[:110],
            x.reporter,f'/device-issues/{x.pk}/review/',x.created_at,'⚒',
            {'status':x.get_status_display()}
        )

    # Overdue tasks
    overdue_qs=Task.objects.filter(
        assigned_to_id__in=user_ids,
        status__in=('todo','doing'),
        due_date__lt=day
    ).select_related('assigned_to','assigned_to__profile')
    for x in overdue_qs:
        days=(day-x.due_date).days if x.due_date else 0
        add_item(
            'task','high' if days>=3 else 'medium',
            'وظیفه عقب‌افتاده',
            f'{x.title} · {days} روز تأخیر',
            x.assigned_to,
            f'/employees/{x.assigned_to.profile.pk}/360/' if hasattr(x.assigned_to,'profile') else '/tasks/',
            timezone.now(),'✓',{'days':days}
        )

    # Attendance exceptions today
    recs={r.user_id:r for r in Attendance.objects.filter(user_id__in=user_ids,date=day).select_related('user')}
    approved_leave_ids=set(LeaveRequest.objects.filter(
        user_id__in=user_ids,status='approved',start_date__lte=day,end_date__gte=day
    ).values_list('user_id',flat=True))

    for u in users:
        if u.id in approved_leave_ids:
            continue
        rec=recs.get(u.id)
        try:
            shift=shift_rule(u,day) or {}
        except Exception:
            shift={}

        if shift.get('is_off'):
            continue

        if rec and rec.check_in:
            current_status=attendance_status_for(u,day,rec.check_in)
            if current_status=='late':
                late_mins=0
                if shift.get('start'):
                    expected=timezone.make_aware(datetime.combine(day,shift['start']),timezone.get_current_timezone())
                    late_mins=max(0,int((rec.check_in-expected).total_seconds()//60))
                add_item(
                    'late','medium','تأخیر امروز',
                    f'ورود {timezone.localtime(rec.check_in).strftime("%H:%M")}'
                    + (f' · {late_mins} دقیقه دیرتر' if late_mins else ''),
                    u,f'/employees/{u.profile.pk}/360/',rec.check_in,'◷',
                    {'late_minutes':late_mins}
                )
        else:
            is_due=True
            if shift.get('start'):
                due_dt=timezone.make_aware(datetime.combine(day,shift['start']),timezone.get_current_timezone())
                is_due=timezone.now() > due_dt + timedelta(minutes=int(shift.get('grace') or 0))
            if is_due:
                add_item(
                    'missing_attendance','critical','ورود امروز ثبت نشده',
                    'از زمان شروع شیفت گذشته و ورود ثبت نشده است.',
                    u,f'/employees/{u.profile.pk}/360/',timezone.now(),'!'
                )

    # Missing report from yesterday, computed directly from DailyReport to avoid helper coupling.
    yesterday=day-timedelta(days=1)
    submitted_ids=set(DailyReport.objects.filter(
        user_id__in=user_ids,
        created_at__date=yesterday
    ).values_list('user_id',flat=True))
    for u in users:
        # Only create the alert when the user had an expected workday.
        try:
            shift=shift_rule(u,yesterday) or {}
            should_report=bool(shift) and not shift.get('is_off',False)
        except Exception:
            should_report=True
        if should_report and u.id not in submitted_ids:
            add_item(
                'report','medium','گزارش روزانه ارسال نشده',
                f'گزارش {format_jalali(yesterday)} ثبت نشده است.',
                u,f'/employees/{u.profile.pk}/360/',timezone.now(),'▤'
            )

    items.sort(key=lambda x:(x['rank'],-x['created_at'].timestamp()))
    counts={
        'all':len(items),
        'critical':sum(1 for x in items if x['priority']=='critical'),
        'high':sum(1 for x in items if x['priority']=='high'),
        'medium':sum(1 for x in items if x['priority']=='medium'),
        'people':len({x['user'].id for x in items if x.get('user')}),
    }

    priority_filter=request.GET.get('priority','')
    kind_filter=request.GET.get('kind','')
    filtered=items
    if priority_filter in ('critical','high','medium','low'):
        filtered=[x for x in filtered if x['priority']==priority_filter]
    if kind_filter:
        filtered=[x for x in filtered if x['kind']==kind_filter]

    return render(request,'core/action_center.html',{
        'items':filtered[:200],
        'counts':counts,
        'priority_filter':priority_filter,
        'kind_filter':kind_filter,
        'today':day,
    })


@executive_required
def executive_workspace(request):
    """Private application-level command center for the configured executive account.

    It deliberately reuses the normal Task model, so delegated items instantly appear
    in the assignee's existing Staff task cartable. This is UI/application isolation,
    not encryption against server/database administrators.
    """
    today=timezone.localdate()

    def audit_exec(action,task,metadata=None):
        try:
            AuditLog.objects.create(
                actor=request.user,
                action=f'executive_{action}',
                path=request.path[:255],
                method=request.method[:10],
                object_type='Task',
                object_id=str(task.pk),
                summary=task.title[:250],
                metadata=metadata or {},
                ip_address=_request_ip(request),
            )
        except Exception:
            pass

    active_people=User.objects.filter(
        is_active=True,
        profile__is_active=True,
    ).select_related('profile','profile__branch').order_by('first_name','last_name','username')

    if request.method=='POST':
        action=(request.POST.get('action') or '').strip()

        if action=='create':
            title=(request.POST.get('title') or '').strip()
            description=(request.POST.get('description') or '').strip()
            priority=(request.POST.get('priority') or 'normal').strip()
            if priority not in {'low','normal','high'}:
                priority='normal'
            bucket=(request.POST.get('bucket') or 'inbox').strip()
            due_date=None
            due_raw=(request.POST.get('due_date') or '').strip()
            if due_raw:
                try:
                    due_date=parse_jalali(due_raw)
                except Exception:
                    messages.error(request,'تاریخ مهلت معتبر نیست. نمونه: ۱۴۰۵/۰۶/۱۳')
                    return redirect('executive_workspace')
            elif bucket=='today':
                due_date=today

            assigned_to=request.user
            assigned_raw=(request.POST.get('assigned_to') or '').strip()
            if assigned_raw and assigned_raw!='self':
                assigned_to=get_object_or_404(active_people,pk=assigned_raw)

            if not title:
                messages.error(request,'عنوان کار را بنویسید.')
                return redirect('executive_workspace')

            task=Task.objects.create(
                title=title,
                description=description,
                assigned_to=assigned_to,
                created_by=request.user,
                due_date=due_date,
                priority=priority,
            )
            audit_exec('create',task,{'assigned_to':assigned_to.username,'due_date':str(due_date or '')})
            if assigned_to.pk!=request.user.pk:
                StaffNotification.objects.create(
                    user=assigned_to,
                    title='وظیفه جدید از دفتر دکتر',
                    message=title[:240],
                    notification_type='task',
                    related_date=due_date or today,
                )
                messages.success(request,f'کار به {assigned_to.get_full_name() or assigned_to.username} واگذار شد.')
            else:
                messages.success(request,'کار به دفتر من اضافه شد.')
            return redirect('executive_workspace')

        if action=='delegate':
            task=get_object_or_404(Task,pk=request.POST.get('task_id'),created_by=request.user)
            assignee=get_object_or_404(active_people,pk=request.POST.get('assigned_to'))
            task.assigned_to=assignee
            if task.status=='done':
                task.status='todo'
            task.save(update_fields=['assigned_to','status','updated_at'])
            audit_exec('delegate',task,{'assigned_to':assignee.username})
            StaffNotification.objects.create(
                user=assignee,
                title='وظیفه جدید از دفتر دکتر',
                message=task.title[:240],
                notification_type='task',
                related_date=task.due_date or today,
            )
            messages.success(request,f'«{task.title}» به {assignee.get_full_name() or assignee.username} واگذار شد.')
            return redirect('executive_workspace')

        if action=='reclaim':
            task=get_object_or_404(Task,pk=request.POST.get('task_id'),created_by=request.user)
            task.assigned_to=request.user
            if task.status=='done':
                task.status='todo'
            task.save(update_fields=['assigned_to','status','updated_at'])
            audit_exec('reclaim',task)
            messages.success(request,'کار به دفتر من برگشت.')
            return redirect('executive_workspace')

        if action=='done':
            task=get_object_or_404(Task,pk=request.POST.get('task_id'),created_by=request.user,assigned_to=request.user)
            task.status='done'
            task.save(update_fields=['status','updated_at'])
            audit_exec('done',task)
            award_task(task)
            messages.success(request,'انجام شد ✓')
            return redirect('executive_workspace')

    own_open=list(Task.objects.filter(
        created_by=request.user,
        assigned_to=request.user,
        status__in=('todo','doing'),
    ).order_by('due_date','-priority','-updated_at'))
    delegated=list(Task.objects.filter(
        created_by=request.user,
        status__in=('todo','doing'),
    ).exclude(assigned_to=request.user).select_related('assigned_to','assigned_to__profile').order_by('due_date','-priority','-updated_at'))

    today_tasks=[t for t in own_open if t.due_date and t.due_date<=today]
    inbox_tasks=[t for t in own_open if not t.due_date]
    later_tasks=[t for t in own_open if t.due_date and t.due_date>today]

    def task_rank(t):
        return ({'high':0,'normal':1,'low':2}.get(t.priority,1), t.due_date or date.max, -int(t.updated_at.timestamp()))

    candidates=sorted(today_tasks+inbox_tasks,key=task_rank)
    the_thing=candidates[0] if candidates else (sorted(later_tasks,key=task_rank)[0] if later_tasks else None)
    would_be_nice=[t for t in candidates if not the_thing or t.pk!=the_thing.pk][:2]
    on_fire=sorted(later_tasks,key=task_rank)[:3]

    delegated_overdue=sum(1 for t in delegated if t.due_date and t.due_date<today)
    done_today=Task.objects.filter(
        created_by=request.user,
        status='done',
        updated_at__date=today,
    ).count()

    return render(request,'core/executive_workspace.html',{
        'today':today,
        'the_thing':the_thing,
        'would_be_nice':would_be_nice,
        'on_fire':on_fire,
        'today_tasks':today_tasks,
        'inbox_tasks':inbox_tasks,
        'later_tasks':later_tasks,
        'delegated':delegated,
        'delegated_overdue':delegated_overdue,
        'done_today':done_today,
        'assignees':active_people.exclude(pk=request.user.pk),
    })

@login_required
def service_worker(request):
    response=HttpResponse("const CACHE='greenlife-staff-v41.0';\nconst STATIC=[\n  '/static/core/app.css?v=v41.0.0',\n  '/static/core/referral.css?v=v40.2',\n  '/static/core/icon-192.png?v=v40.2',\n  '/static/core/icon-512.png?v=v40.2',\n  '/static/core/manifest.webmanifest?v=v40.2'\n];\nself.addEventListener('install',e=>{\n  e.waitUntil(caches.open(CACHE).then(c=>c.addAll(STATIC).catch(()=>{})));\n  self.skipWaiting();\n});\nself.addEventListener('activate',e=>{\n  e.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(k=>k!==CACHE).map(k=>caches.delete(k)))));\n  self.clients.claim();\n});\nself.addEventListener('fetch',e=>{\n  if(e.request.method!=='GET') return;\n  const url=new URL(e.request.url);\n  if(url.origin!==location.origin) return;\n  // Network-first for dynamic authenticated pages so stale staff data is not shown.\n  if(url.pathname.startsWith('/static/')){\n    e.respondWith(caches.match(e.request).then(r=>r||fetch(e.request).then(resp=>{\n      const copy=resp.clone(); caches.open(CACHE).then(c=>c.put(e.request,copy)); return resp;\n    })));\n    return;\n  }\n  e.respondWith(fetch(e.request).catch(()=>caches.match(e.request)));\n});\n", content_type='application/javascript')
    response['Cache-Control']='no-cache, no-store, must-revalidate'
    return response
