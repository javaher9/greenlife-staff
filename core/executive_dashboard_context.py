from datetime import timedelta
from decimal import Decimal
from django.db.models import Count, Sum
from django.utils import timezone
from .models import Attendance, DailyReport, FinancialTransaction, StaffNotification, Task, VisitAppointment, ReferralLead, ReferralSale, MeetingMinute
MILLION=Decimal('10000000')
COLORS=['#25e0a1','#20a4ff','#8b5cf6','#ffb82e','#ff4f91','#19d4d0']

def build_executive_summary(user):
    today=timezone.localdate(); start=today.replace(day=1)
    inc=FinancialTransaction.objects.filter(entry_type='inc',review_status='approved')
    def m(q): return Decimal(q.aggregate(v=Sum('amount'))['v'] or 0)/MILLION
    daily=[]
    for i in range(29,-1,-1):
        d=today-timedelta(days=i); daily.append({'day':d.day,'value':float(m(inc.filter(occurred_at=d)))})
    peak=max([x['value'] for x in daily],default=0) or 1
    pts=' '.join(f"{round(i*100/29,1)},{round(48-(x['value']/peak*42),1)}" for i,x in enumerate(daily))
    rows=list(inc.filter(occurred_at__gte=start,occurred_at__lte=today).values('branch__name').annotate(v=Sum('amount')).order_by('-v'))
    maxb=max([r['v'] or 0 for r in rows],default=0) or 1
    branches=[{'name':r['branch__name'] or 'بدون شعبه','amount_m':Decimal(r['v'] or 0)/MILLION,'percent':round(float(Decimal(r['v'] or 0)/Decimal(maxb)*100),1),'color':COLORS[i%len(COLORS)]} for i,r in enumerate(rows)]
    leads=ReferralLead.objects.all(); src=list(leads.values('source').annotate(n=Count('id')).order_by('-n')[:5]); total_src=sum(x['n'] for x in src) or 1
    sources=[{'name':x['source'] or 'سایر','value':x['n'],'pct':round(x['n']*100/total_src),'color':COLORS[i%len(COLORS)]} for i,x in enumerate(src)]
    appts=VisitAppointment.objects.filter(appointment_date=today); appt_rows=list(appts.values('status').annotate(n=Count('id')).order_by('-n')); total_appt=sum(x['n'] for x in appt_rows) or 1
    appointments=[{'name':dict(VisitAppointment.STATUS).get(x['status'],x['status']),'value':x['n'],'pct':round(x['n']*100/total_appt),'color':COLORS[i%len(COLORS)]} for i,x in enumerate(appt_rows)]
    present=Attendance.objects.filter(date=today,check_in__isnull=False).values('user_id').distinct().count(); late=Attendance.objects.filter(date=today,status='late').values('user_id').distinct().count()
    open_tasks=Task.objects.exclude(status='done'); meetings=MeetingMinute.objects.filter(meeting_date__gte=today-timedelta(days=30))
    return {'finance_today_m':m(inc.filter(occurred_at=today)),'finance_month_m':m(inc.filter(occurred_at__gte=start,occurred_at__lte=today)),'sales_line_points':pts,'sales_daily':daily,'branch_sales':branches,'lead_sources':sources,'appointment_mix':appointments,'present_today':present,'late_today':late,'open_tasks':open_tasks.count(),'overdue_tasks':open_tasks.filter(due_date__lt=today).count(),'urgent_tasks':open_tasks.filter(priority='high').select_related('assigned_to').order_by('due_date','-id')[:4],'appointments_today':appts.count(),'reports_today':DailyReport.objects.filter(date=today).count(),'unread_notifications':StaffNotification.objects.filter(user=user,is_read=False).count(),'meetings_30d':meetings.count(),'open_meetings':meetings.filter(status='open').count(),'open_leads':leads.filter(status__in=('new','contacted','appointment','visited')).count(),'leads_today':leads.filter(created_at__date=today).count(),'won_month':ReferralSale.objects.filter(sale_date__gte=start,status__in=('approved','paid')).values('lead_id').distinct().count(),'followups':leads.filter(next_follow_up__lte=today).exclude(status__in=('won','lost')).count()}
