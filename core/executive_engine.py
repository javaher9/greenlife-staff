from datetime import timedelta, date
from django.contrib.auth.models import User
from django.db.models import Sum, Q
from django.utils import timezone
from .models import Attendance, Task, DailyReport, LeaveRequest, FinancialTransaction, PerformanceGoal, EmployeeDocument, ShiftAssignment, ManagementEvent
from .operations import auto_kpi, missing_report_days
from .jalali import gregorian_to_jalali, jalali_to_gregorian

def scoped_users(branch=None):
    qs=User.objects.filter(profile__is_active=True).select_related('profile','profile__branch')
    return qs.filter(profile__branch=branch) if branch else qs

def ceo_score(branch=None, day=None):
    day=day or timezone.localdate()
    start=day-timedelta(days=29)
    users=list(scoped_users(branch))
    if not users:
        return {'score':100,'people':100,'operations':100,'revenue':100,'discipline':100,'reasons':['پرسنل فعالی در محدوده انتخاب‌شده وجود ندارد.']}
    user_ids=[u.id for u in users]

    # People: average automatic KPI.
    kpis=[auto_kpi(u,start,day)['score'] for u in users]
    people=round(sum(kpis)/len(kpis)) if kpis else 100

    # Operations: overdue task pressure + completion.
    tasks=Task.objects.filter(assigned_to_id__in=user_ids,created_at__date__lte=day)
    due=tasks.filter(due_date__lte=day)
    total_due=due.count()
    done_due=due.filter(status='done').count()
    operations=round(100*done_due/total_due) if total_due else 100

    # Discipline: punctuality and report compliance.
    att=Attendance.objects.filter(user_id__in=user_ids,date__range=(start,day),check_in__isnull=False)
    att_n=att.count(); late=att.filter(status='late').count()
    punctual=round(100*(att_n-late)/att_n) if att_n else 100
    missing_reports=sum(len(missing_report_days(u,days=30,end=day-timedelta(days=1))) for u in users)
    possible=max(1,len(users)*30)
    report_score=max(0,round(100*(1-missing_reports/possible)))
    discipline=round(.65*punctual+.35*report_score)

    # Revenue: last 7 days vs previous 7 days. Neutral 85 if no baseline.
    cur_start=day-timedelta(days=6); prev_end=cur_start-timedelta(days=1); prev_start=prev_end-timedelta(days=6)
    cur=FinancialTransaction.objects.filter(occurred_at__date__range=(cur_start,day))
    prev=FinancialTransaction.objects.filter(occurred_at__date__range=(prev_start,prev_end))
    if branch: cur=cur.filter(branch=branch); prev=prev.filter(branch=branch)
    cur_v=float(cur.aggregate(x=Sum('amount'))['x'] or 0); prev_v=float(prev.aggregate(x=Sum('amount'))['x'] or 0)
    if prev_v>0:
        ratio=cur_v/prev_v
        revenue=max(0,min(100,round(85+(ratio-1)*75)))
    else:
        revenue=85 if cur_v else 70

    score=round(.30*people+.25*operations+.25*revenue+.20*discipline)
    reasons=[]
    parts={'نیروی انسانی':people,'عملیات':operations,'درآمد':revenue,'انضباط':discipline}
    for label,value in sorted(parts.items(),key=lambda x:x[1]):
        if value<80: reasons.append(f'{label} با امتیاز {value} بیشترین نیاز به توجه را دارد.')
    if late: reasons.append(f'در ۳۰ روز اخیر {late} مورد تأخیر ثبت شده است.')
    overdue=tasks.exclude(status='done').filter(due_date__lt=day).count()
    if overdue: reasons.append(f'{overdue} Task از موعد گذشته هنوز بسته نشده است.')
    if missing_reports: reasons.append(f'{missing_reports} گزارش شبانه در بازه بررسی جا افتاده است.')
    if not reasons: reasons.append('شاخص‌های اصلی در محدوده سالم قرار دارند.')
    return {'score':score,'people':people,'operations':operations,'revenue':revenue,'discipline':discipline,'reasons':reasons,
            'revenue_current_7d':cur_v,'revenue_previous_7d':prev_v}

def trend_alerts(branch=None, day=None):
    day=day or timezone.localdate()
    users=scoped_users(branch); ids=list(users.values_list('id',flat=True))
    alerts=[]
    cur_start=day-timedelta(days=6); prev_end=cur_start-timedelta(days=1); prev_start=prev_end-timedelta(days=6)

    # Revenue trend.
    cur=FinancialTransaction.objects.filter(occurred_at__date__range=(cur_start,day))
    prev=FinancialTransaction.objects.filter(occurred_at__date__range=(prev_start,prev_end))
    if branch: cur=cur.filter(branch=branch); prev=prev.filter(branch=branch)
    cv=float(cur.aggregate(x=Sum('amount'))['x'] or 0); pv=float(prev.aggregate(x=Sum('amount'))['x'] or 0)
    if pv:
        change=round((cv-pv)*100/pv,1)
        if change<=-12: alerts.append({'level':'danger','title':'افت درآمد','text':f'درآمد ۷ روز اخیر {abs(change)}٪ پایین‌تر از ۷ روز قبل است.','value':change})
        elif change>=15: alerts.append({'level':'good','title':'رشد درآمد','text':f'درآمد ۷ روز اخیر {change}٪ بالاتر از ۷ روز قبل است.','value':change})

    # Late trend overall.
    def late_rate(a,b):
        qs=Attendance.objects.filter(user_id__in=ids,date__range=(a,b),check_in__isnull=False)
        n=qs.count()
        return (100*qs.filter(status='late').count()/n) if n else 0
    lr=late_rate(cur_start,day); pr=late_rate(prev_start,prev_end)
    if lr-pr>=8 and lr>=12:
        alerts.append({'level':'warning','title':'روند افزایشی تأخیر','text':f'نرخ تأخیر از {pr:.0f}٪ به {lr:.0f}٪ رسیده است.','value':round(lr-pr,1)})

    # Individual repeated lateness.
    for u in users:
        c=Attendance.objects.filter(user=u,date__range=(cur_start,day),status='late').count()
        p=Attendance.objects.filter(user=u,date__range=(prev_start,prev_end),status='late').count()
        if c>=3 and c>p:
            alerts.append({'level':'warning','title':'تأخیر تکرارشونده','text':f'{u.get_full_name() or u.username} در ۷ روز اخیر {c} بار تأخیر داشته است.','user_id':u.id})

    # KPI deterioration.
    for u in users:
        cur_k=auto_kpi(u,day-timedelta(days=29),day)['score']
        prev_k=auto_kpi(u,day-timedelta(days=59),day-timedelta(days=30))['score']
        if prev_k-cur_k>=10:
            alerts.append({'level':'danger','title':'افت KPI','text':f'KPI {u.get_full_name() or u.username} از {prev_k} به {cur_k} کاهش یافته است.','user_id':u.id})
    return alerts[:20]

def calendar_events(branch=None, jy=None, jm=None):
    today=timezone.localdate()
    if jy is None or jm is None:
        jy,jm,_=gregorian_to_jalali(today.year,today.month,today.day)
    gy,gm,gd=jalali_to_gregorian(jy,jm,1)
    start=date(gy,gm,gd)
    if jm==12:
        ngy,ngm,ngd=jalali_to_gregorian(jy+1,1,1)
    else:
        ngy,ngm,ngd=jalali_to_gregorian(jy,jm+1,1)
    end=date(ngy,ngm,ngd)-timedelta(days=1)
    users=scoped_users(branch); ids=list(users.values_list('id',flat=True))
    events=[]

    def add(d,kind,title,detail='',url=''):
        events.append({'date':d,'kind':kind,'title':title,'detail':detail,'url':url})

    for x in LeaveRequest.objects.filter(user_id__in=ids,status='approved',start_date__lte=end,end_date__gte=start).select_related('user'):
        d=max(start,x.start_date)
        while d<=min(end,x.end_date):
            add(d,'leave',x.get_request_type_display(),x.user.get_full_name() or x.user.username)
            d+=timedelta(days=1)
    for x in Task.objects.filter(assigned_to_id__in=ids,due_date__range=(start,end)).select_related('assigned_to'):
        add(x.due_date,'task','مهلت Task',x.title,f'/tasks/{x.id}/')
    for x in PerformanceGoal.objects.filter(Q(employee_id__in=ids)|Q(branch=branch) if branch else Q(employee_id__in=ids),end_date__range=(start,end)):
        add(x.end_date,'goal','پایان هدف',x.title,'/goals/')
    docs=EmployeeDocument.objects.filter(employee__user_id__in=ids,expiry_date__range=(start,end)).select_related('employee__user')
    for x in docs: add(x.expiry_date,'document','انقضای مدرک',f'{x.employee.user.get_full_name() or x.employee.user.username} · {x.title}',f'/employees/{x.employee_id}/file/')
    custom=ManagementEvent.objects.filter(date__range=(start,end))
    if branch: custom=custom.filter(Q(branch=branch)|Q(branch__isnull=True))
    for x in custom: add(x.date,'event',x.title,x.get_event_type_display())
    shifts=ShiftAssignment.objects.filter(user_id__in=ids,date__range=(start,end)).select_related('user','shift')
    for x in shifts: add(x.date,'shift','شیفت',f'{x.user.get_full_name() or x.user.username} · {x.shift.name}')
    # birthdays repeat annually based on Jalali month/day of stored birth date.
    for u in users:
        bd=getattr(u.profile,'birth_date',None)
        if bd:
            _,bjm,bjd=gregorian_to_jalali(bd.year,bd.month,bd.day)
            if bjm==jm:
                try:
                    by,bm,bdg=jalali_to_gregorian(jy,bjm,bjd)
                    add(date(by,bm,bdg),'birthday','تولد',u.get_full_name() or u.username)
                except Exception: pass
    return {'jy':jy,'jm':jm,'start':start,'end':end,'events':events}
