import os
from datetime import datetime, timedelta
from decimal import Decimal
from django.contrib.auth.models import User
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from .models import (Attendance, AttendanceCorrectionRequest, DailyReport, LeaveRequest,
                     ScoreEvent, ShiftAssignment, ShiftGroup, StaffNotification, Task, FinancialTransaction)
from .jalali import format_jalali

REPORT_MISSING_PENALTY=int(os.getenv('REPORT_MISSING_PENALTY','-2'))
ON_TIME_POINTS=int(os.getenv('ON_TIME_POINTS','5'))
REPORT_POINTS=int(os.getenv('REPORT_POINTS','3'))
TASK_POINTS=int(os.getenv('TASK_POINTS','4'))


def approved_leave(user, day):
    return LeaveRequest.objects.filter(user=user,status='approved',start_date__lte=day,end_date__gte=day).first()


def assignment_for(user, day):
    return ShiftAssignment.objects.select_related('shift','shift__branch').filter(user=user,date=day,shift__is_active=True).first()


def shift_rule(user, day):
    # Priority:
    # 1) One-day personal override
    # 2) Employee shift group
    # 3) Branch default hours
    assignment=assignment_for(user,day)
    if assignment:
        return {
            'name':assignment.shift.name,
            'start':assignment.shift.start_time,
            'end':assignment.shift.end_time,
            'grace':assignment.shift.grace_minutes,
            'report_required':assignment.shift.report_required,
            'assignment':assignment,
            'source':'personal',
        }

    profile=getattr(user,'profile',None)
    group=getattr(profile,'shift_group',None) if profile else None
    if group and group.is_active and group.default_shift and group.default_shift.is_active:
        shift=group.default_shift
        return {
            'name':f'{group.name} - {shift.name}',
            'start':shift.start_time,
            'end':shift.end_time,
            'grace':shift.grace_minutes,
            'report_required':shift.report_required,
            'assignment':None,
            'source':'group',
            'group':group,
        }

    branch=getattr(profile,'branch',None) if profile else None
    if branch:
        return {
            'name':'ساعت کاری شعبه',
            'start':branch.work_start,
            'end':branch.work_end,
            'grace':branch.grace_minutes,
            'report_required':True,
            'assignment':None,
            'source':'branch',
        }

    return {
        'name':'ساعت پیش‌فرض',
        'start':None,
        'end':None,
        'grace':0,
        'report_required':True,
        'assignment':None,
        'source':'default',
    }


def attendance_status_for(user, day, check_in):
    leave=approved_leave(user,day)
    if leave: return 'leave'
    if not check_in: return 'absent'
    rule=shift_rule(user,day)
    if not rule['start']: return 'present'
    local=timezone.localtime(check_in)
    threshold=datetime.combine(day,rule['start'])+timedelta(minutes=rule['grace'])
    return 'late' if local.replace(tzinfo=None)>threshold else 'present'


def overtime_minutes(record):
    if not record or not record.check_out: return 0
    rule=shift_rule(record.user,record.date)
    if not rule['end']: return 0
    local_out=timezone.localtime(record.check_out).replace(tzinfo=None)
    expected=datetime.combine(record.date,rule['end'])
    # Overnight shifts: end <= start means expected end next day.
    if rule['start'] and rule['end']<=rule['start']: expected += timedelta(days=1)
    return max(0,int((local_out-expected).total_seconds()//60))


def report_exists(user, day):
    return DailyReport.objects.filter(user=user,created_at__date=day).exists()


def report_required(user, day):
    if approved_leave(user,day): return False
    rule=shift_rule(user,day)
    return bool(rule['report_required'])


def missing_report_days(user, days=31, end=None):
    end=end or timezone.localdate()
    start=end-timedelta(days=days-1)
    result=[]
    d=start
    profile=getattr(user,'profile',None)
    while d<=end:
        if profile and profile.start_date and d<profile.start_date:
            d+=timedelta(days=1); continue
        if report_required(user,d) and not report_exists(user,d): result.append(d)
        d+=timedelta(days=1)
    return result


def apply_missing_report_penalties(day=None):
    day=day or (timezone.localdate()-timedelta(days=1))
    users=User.objects.filter(profile__is_active=True).select_related('profile','profile__branch')
    penalized=0
    for user in users:
        if user.profile.start_date and day<user.profile.start_date: continue
        if not report_required(user,day) or report_exists(user,day): continue
        key=f'گزارش ارسال نشده - {day.isoformat()}'
        event,created=ScoreEvent.objects.get_or_create(user=user,event_date=day,reason='penalty',description=key,
                                                       defaults={'points':REPORT_MISSING_PENALTY})
        if created:
            penalized+=1
            recent=missing_report_days(user,days=31,end=day)
            StaffNotification.objects.create(
                user=user,title='گزارش روزانه ارسال نشده',notification_type='missing_report',related_date=day,
                message=f'گزارش شب {format_jalali(day)} ارسال نشده و {abs(REPORT_MISSING_PENALTY)} امتیاز کسر شد. در ۳۱ روز اخیر {len(recent)} شب گزارش ارسال نشده است.')
    return penalized


def award_report(user, day):
    if not ScoreEvent.objects.filter(user=user,event_date=day,reason='report',description='گزارش روزانه').exists():
        ScoreEvent.objects.create(user=user,event_date=day,reason='report',points=REPORT_POINTS,description='گزارش روزانه')


def award_task(task):
    if task.status=='done' and not ScoreEvent.objects.filter(user=task.assigned_to,reason='task',description=f'TASK#{task.pk}').exists():
        ScoreEvent.objects.create(user=task.assigned_to,event_date=timezone.localdate(),reason='task',points=TASK_POINTS,description=f'TASK#{task.pk}')


def auto_kpi(user, start, end):
    total_days=(end-start).days+1
    attendance=Attendance.objects.filter(user=user,date__range=(start,end))
    present=attendance.filter(status='present').count(); late=attendance.filter(status='late').count()
    scheduled=max(1,attendance.count()+len([d for d in missing_report_days(user,total_days,end=end) if start<=d<=end]))
    attendance_score=max(0,min(100,round((present + late*.5)/scheduled*100)))
    tasks=Task.objects.filter(assigned_to=user,due_date__range=(start,end)); task_total=tasks.count(); done=tasks.filter(status='done').count()
    task_score=100 if task_total==0 else round(done/task_total*100)
    expected_reports=max(0,sum(1 for i in range(total_days) if report_required(user,start+timedelta(days=i))))
    report_count=DailyReport.objects.filter(user=user,created_at__date__range=(start,end)).values('created_at__date').distinct().count()
    report_score=100 if expected_reports==0 else min(100,round(report_count/expected_reports*100))
    branch=getattr(getattr(user,'profile',None),'branch',None)
    revenue_score=100
    revenue=Decimal('0')
    target=Decimal(os.getenv('BRANCH_REVENUE_TARGET_DAILY','0') or '0') * Decimal(str(total_days))
    if branch:
        revenue=FinancialTransaction.objects.filter(branch=branch,occurred_at__date__range=(start,end)).aggregate(x=Sum('amount'))['x'] or Decimal('0')
        if target>0: revenue_score=max(0,min(120,round(float(revenue/target*100))))
    final=round(attendance_score*.40 + task_score*.25 + report_score*.20 + min(100,revenue_score)*.15)
    return {'score':final,'attendance':attendance_score,'tasks':task_score,'reports':report_score,'revenue':revenue_score,
            'revenue_total':str(revenue),'period_start':str(start),'period_end':str(end)}


def approve_correction(obj, reviewer, status, note=''):
    obj.status=status; obj.manager_note=note; obj.reviewed_by=reviewer; obj.reviewed_at=timezone.now()
    if status=='approved':
        rec,_=Attendance.objects.get_or_create(user=obj.user,date=obj.date,defaults={'branch':getattr(obj.user.profile,'branch',None)})
        if obj.requested_check_in is not None: rec.check_in=obj.requested_check_in
        if obj.requested_check_out is not None: rec.check_out=obj.requested_check_out
        rec.status=attendance_status_for(obj.user,obj.date,rec.check_in); rec.save(); obj.attendance=rec
    obj.save()
    StaffNotification.objects.create(user=obj.user,title='نتیجه درخواست اصلاح حضور',notification_type='attendance_correction',related_date=obj.date,
        message=f'درخواست اصلاح حضور {format_jalali(obj.date)} {obj.get_status_display()} شد.' + (f' توضیح مدیر: {note}' if note else ''))
    return obj
