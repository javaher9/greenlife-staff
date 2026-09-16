from datetime import timedelta
from decimal import Decimal
from django.db.models import Count, Sum
from django.utils import timezone
from .models import Attendance, DailyReport, FinancialTransaction, StaffNotification, Task, VisitAppointment, ReferralLead, ReferralSale
MILLION_TOMAN_RIAL=Decimal('10000000')

def build_executive_summary(user):
    today=timezone.localdate(); month_start=today.replace(day=1)
    approved=FinancialTransaction.objects.filter(entry_type='inc',review_status='approved')
    today_total=approved.filter(occurred_at=today).aggregate(v=Sum('amount'))['v'] or 0
    month_total=approved.filter(occurred_at__gte=month_start,occurred_at__lte=today).aggregate(v=Sum('amount'))['v'] or 0
    rows=list(approved.filter(occurred_at__gte=month_start,occurred_at__lte=today).values('branch__name').annotate(v=Sum('amount')).order_by('-v'))
    max_branch=max([r['v'] or 0 for r in rows],default=0) or 1; palette=['#8b5cf6','#38bdf8','#22c55e','#f59e0b','#ec4899','#14b8a6']
    branch_sales=[]
    for i,r in enumerate(rows):
        amount=Decimal(r['v'] or 0); branch_sales.append({'name':r['branch__name'] or 'بدون شعبه','amount_m':amount/MILLION_TOMAN_RIAL,'percent':min(100,round(float(amount/Decimal(max_branch)*100),1)),'color':palette[i%len(palette)]})
    open_tasks=Task.objects.exclude(status='done'); sources=ReferralLead.objects.values('source').annotate(n=Count('id')).order_by('-n')[:4]
    return {'finance_today_m':Decimal(today_total)/MILLION_TOMAN_RIAL,'finance_month_m':Decimal(month_total)/MILLION_TOMAN_RIAL,'branch_sales':branch_sales,'present_today':Attendance.objects.filter(date=today,check_in__isnull=False).values('user_id').distinct().count(),'late_today':Attendance.objects.filter(date=today,status='late').values('user_id').distinct().count(),'open_tasks':open_tasks.count(),'overdue_tasks':open_tasks.filter(due_date__lt=today).count(),'urgent_tasks':open_tasks.filter(priority='high').select_related('assigned_to').order_by('due_date','-id')[:5],'appointments_today':VisitAppointment.objects.filter(appointment_date=today).count(),'reports_today':DailyReport.objects.filter(date=today).count(),'unread_notifications':StaffNotification.objects.filter(user=user,is_read=False).count(),'meetings_30d':Task.objects.filter(description__icontains='صورت جلسه',created_at__date__gte=today-timedelta(days=30)).count(),'open_leads':ReferralLead.objects.filter(status__in=('new','contacted','appointment','visited')).count(),'leads_today':ReferralLead.objects.filter(created_at__date=today).count(),'won_month':ReferralSale.objects.filter(sale_date__gte=month_start,status__in=('approved','paid')).values('lead_id').distinct().count(),'followups':ReferralLead.objects.filter(next_follow_up__lte=today).exclude(status__in=('won','lost')).count(),'referral_highlights':[{'name':r['source'] or 'بدون منبع','detail':'تعداد لید ثبت‌شده','value':r['n']} for r in sources]}
