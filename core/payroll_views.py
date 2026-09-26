from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .jalali import gregorian_to_jalali, jalali_to_gregorian
from .models import (
    Attendance, Branch, EmployeeProfile, FinancialTransaction, PayrollMonthlyAdjustment,
    PayrollRule, PayrollSnapshot, ReferralSale,
)

MONTH_NAMES=[
    'فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور',
    'مهر','آبان','آذر','دی','بهمن','اسفند',
]
ZERO=Decimal('0')


def _payroll_admin(view):
    @wraps(view)
    @login_required
    def wrapper(request,*args,**kwargs):
        profile=getattr(request.user,'profile',None)
        is_exec=(getattr(request.user,'username','') or '').lower() in settings.EXECUTIVE_USERNAMES
        if not (request.user.is_superuser or is_exec or (profile and profile.role=='admin')):
            raise PermissionDenied('Payroll access denied.')
        return view(request,*args,**kwargs)
    return wrapper


def _decimal(value, default=ZERO):
    if value is None:
        return default
    text=str(value).translate(str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789'))
    text=text.replace(',','').replace('٬','').strip()
    if not text:
        return default
    try:
        return Decimal(text)
    except (InvalidOperation,ValueError,TypeError):
        return default


def _money(value):
    try:
        return f'{int(Decimal(value or 0)):,.0f}'
    except Exception:
        return '0'


def _month_bounds(jy,jm):
    gy,gm,gd=jalali_to_gregorian(jy,jm,1)
    start=date(gy,gm,gd)
    njy,njm=(jy+1,1) if jm==12 else (jy,jm+1)
    egy,egm,egd=jalali_to_gregorian(njy,njm,1)
    end=date(egy,egm,egd)
    return start,end


def _previous_month(jy,jm,steps=1):
    for _ in range(steps):
        if jm==1:
            jy,jm=jy-1,12
        else:
            jm-=1
    return jy,jm


def _sale_total_toman(profile,rule,start,end):
    source=(rule.commission_source if rule else 'auto') or 'auto'
    if source=='auto':
        if profile.role=='call_center':
            source='call_center'
        elif profile.role=='consultant':
            source='recorded_sale'
        else:
            source='none'
    if source=='none':
        return ZERO

    if source=='call_center':
        start_dt=timezone.make_aware(datetime.combine(start,time.min))
        end_dt=timezone.make_aware(datetime.combine(end,time.min))
        rial=FinancialTransaction.objects.filter(
            entry_type='inc',review_status='approved',
            call_center_owner=profile.user,
            occurred_at__gte=start_dt,occurred_at__lt=end_dt,
        ).aggregate(total=Sum('amount'))['total'] or ZERO
        return (Decimal(rial)/Decimal('10')).quantize(Decimal('1'),rounding=ROUND_HALF_UP)

    total=ReferralSale.objects.filter(
        recorded_by=profile.user,
        status__in=('approved','paid'),
        sale_date__gte=start,sale_date__lt=end,
    ).aggregate(total=Sum('amount'))['total'] or ZERO
    return Decimal(total).quantize(Decimal('1'),rounding=ROUND_HALF_UP)


def _live_payroll_row(profile,start,end):
    rule=PayrollRule.objects.filter(profile=profile).first()
    adjustment=PayrollMonthlyAdjustment.objects.filter(profile=profile,month_start=start).first()

    base=Decimal(rule.base_salary_toman) if rule else ZERO
    percent=Decimal(rule.commission_percent) if rule else ZERO
    sales=_sale_total_toman(profile,rule,start,end)
    returned=Decimal(adjustment.returned_sales_toman) if adjustment else ZERO
    effective_return=min(max(returned,ZERO),max(sales,ZERO))
    commission=(sales*percent/Decimal('100')).quantize(Decimal('1'),rounding=ROUND_HALF_UP)
    return_deduction=(effective_return*percent/Decimal('100')).quantize(Decimal('1'),rounding=ROUND_HALF_UP)

    mission=Decimal(adjustment.mission_toman) if adjustment else ZERO
    bonus=Decimal(adjustment.bonus_toman) if adjustment else ZERO
    absence_deduction=Decimal(adjustment.absence_deduction_toman) if adjustment else ZERO
    late_deduction=Decimal(adjustment.late_deduction_toman) if adjustment else ZERO
    salary_deduction=Decimal(adjustment.salary_deduction_toman) if adjustment else ZERO
    advance=Decimal(adjustment.advance_toman) if adjustment else ZERO
    insurance=Decimal(adjustment.insurance_toman) if adjustment else ZERO

    attendance=Attendance.objects.filter(user=profile.user,date__gte=start,date__lt=end)
    absence_count=attendance.filter(status='absent').count()
    late_count=attendance.filter(status='late').count()
    deductions=return_deduction+absence_deduction+late_deduction+salary_deduction+advance+insurance
    net=base+commission+mission+bonus-deductions

    return {
        'profile':profile,'rule':rule,'adjustment':adjustment,'closed':False,
        'base':base,'sales':sales,'returned_sales':returned,'percent':percent,
        'commission':commission,'return_deduction':return_deduction,
        'mission':mission,'bonus':bonus,'absence_count':absence_count,'late_count':late_count,
        'absence_deduction':absence_deduction,'late_deduction':late_deduction,
        'salary_deduction':salary_deduction,'advance':advance,'insurance':insurance,
        'deductions':deductions,'net':net,
    }


def _payroll_row(profile,start,end,force_live=False):
    if not force_live:
        snap=PayrollSnapshot.objects.filter(profile=profile,month_start=start).first()
        if snap:
            returned=Decimal(snap.returned_sales_toman)
            sales=Decimal(snap.sales_toman)
            percent=Decimal(snap.commission_percent)
            return_deduction=(min(max(returned,ZERO),max(sales,ZERO))*percent/Decimal('100')).quantize(Decimal('1'),rounding=ROUND_HALF_UP)
            deductions=(
                return_deduction+Decimal(snap.absence_deduction_toman)+Decimal(snap.late_deduction_toman)+
                Decimal(snap.salary_deduction_toman)+Decimal(snap.advance_toman)+Decimal(snap.insurance_toman)
            )
            return {
                'profile':profile,'rule':PayrollRule.objects.filter(profile=profile).first(),
                'adjustment':PayrollMonthlyAdjustment.objects.filter(profile=profile,month_start=start).first(),
                'closed':True,'closed_at':snap.closed_at,
                'base':Decimal(snap.base_salary_toman),'sales':sales,'returned_sales':returned,
                'percent':percent,'commission':Decimal(snap.commission_toman),
                'return_deduction':return_deduction,'mission':Decimal(snap.mission_toman),
                'bonus':Decimal(snap.bonus_toman),'absence_count':snap.absence_count,'late_count':snap.late_count,
                'absence_deduction':Decimal(snap.absence_deduction_toman),
                'late_deduction':Decimal(snap.late_deduction_toman),
                'salary_deduction':Decimal(snap.salary_deduction_toman),
                'advance':Decimal(snap.advance_toman),'insurance':Decimal(snap.insurance_toman),
                'deductions':deductions,'net':Decimal(snap.net_salary_toman),
            }
    return _live_payroll_row(profile,start,end)


def _decorate(row):
    row=row.copy()
    for key in (
        'base','sales','returned_sales','commission','return_deduction','mission','bonus',
        'absence_deduction','late_deduction','salary_deduction','advance','insurance','deductions','net',
    ):
        row[key+'_display']=_money(row[key])
    pct=row.get('percent') or ZERO
    row['percent_display']=f'{pct.normalize()}' if pct else '0'
    return row


def _redirect_period(jy,jm,employee=None,branch=None,anchor=''):
    params={'jy':jy,'jm':jm}
    if employee:
        params['employee']=employee
    if branch:
        params['branch']=branch
    url=reverse('payroll_dashboard')+'?'+urlencode(params)
    return redirect(url+(anchor or ''))


@_payroll_admin
def payroll_dashboard(request):
    today=timezone.localdate()
    current_jy,current_jm,_=gregorian_to_jalali(today.year,today.month,today.day)
    try:
        jy=int(request.GET.get('jy') or request.POST.get('jy') or current_jy)
        jm=int(request.GET.get('jm') or request.POST.get('jm') or current_jm)
    except (TypeError,ValueError):
        jy,jm=current_jy,current_jm
    if jm<1 or jm>12 or jy<1390 or jy>1500:
        jy,jm=current_jy,current_jm
    start,end=_month_bounds(jy,jm)

    branch_id=(request.GET.get('branch') or request.POST.get('branch') or '').strip()
    employee_id=(request.GET.get('employee') or request.POST.get('profile_id') or '').strip()

    if request.method=='POST':
        action=(request.POST.get('action') or '').strip()
        if action=='save_rule':
            profile=get_object_or_404(EmployeeProfile,pk=request.POST.get('profile_id'),is_active=True)
            rule,_=PayrollRule.objects.get_or_create(profile=profile)
            rule.base_salary_toman=max(_decimal(request.POST.get('base_salary_toman')),ZERO)
            percent=max(_decimal(request.POST.get('commission_percent')),ZERO)
            rule.commission_percent=min(percent,Decimal('100'))
            source=(request.POST.get('commission_source') or 'auto').strip()
            if source not in dict(PayrollRule.COMMISSION_SOURCE):
                source='auto'
            rule.commission_source=source
            rule.note=(request.POST.get('rule_note') or '').strip()[:500]
            rule.updated_by=request.user
            rule.save()
            insured=(request.POST.get('insured') or '').strip()
            profile.is_insured=True if insured=='yes' else False if insured=='no' else None
            profile.save(update_fields=['is_insured'])
            messages.success(request,f'تنظیمات حقوق {profile} ذخیره شد.')
            return _redirect_period(jy,jm,profile.pk,branch_id,'#person-detail')

        if action=='save_adjustment':
            profile=get_object_or_404(EmployeeProfile,pk=request.POST.get('profile_id'),is_active=True)
            adjustment,_=PayrollMonthlyAdjustment.objects.get_or_create(profile=profile,month_start=start)
            fields=(
                'mission_toman','returned_sales_toman','absence_deduction_toman','late_deduction_toman',
                'bonus_toman','salary_deduction_toman','advance_toman','insurance_toman',
            )
            for field in fields:
                setattr(adjustment,field,max(_decimal(request.POST.get(field)),ZERO))
            adjustment.note=(request.POST.get('adjustment_note') or '').strip()
            adjustment.updated_by=request.user
            adjustment.save()
            messages.success(request,f'اقلام حقوق {MONTH_NAMES[jm-1]} برای {profile} ذخیره شد.')
            return _redirect_period(jy,jm,profile.pk,branch_id,'#person-detail')

        if action=='close_month':
            profiles=EmployeeProfile.objects.filter(is_active=True,user__is_active=True).exclude(role='referrer').select_related('user','branch')
            with transaction.atomic():
                for profile in profiles:
                    row=_live_payroll_row(profile,start,end)
                    PayrollSnapshot.objects.update_or_create(
                        profile=profile,month_start=start,
                        defaults={
                            'base_salary_toman':row['base'],'sales_toman':row['sales'],
                            'returned_sales_toman':row['returned_sales'],'commission_percent':row['percent'],
                            'commission_toman':row['commission'],'mission_toman':row['mission'],
                            'bonus_toman':row['bonus'],'absence_count':row['absence_count'],
                            'late_count':row['late_count'],'absence_deduction_toman':row['absence_deduction'],
                            'late_deduction_toman':row['late_deduction'],
                            'salary_deduction_toman':row['salary_deduction'],'advance_toman':row['advance'],
                            'insurance_toman':row['insurance'],'net_salary_toman':row['net'],
                            'closed_by':request.user,
                        },
                    )
            messages.success(request,f'حقوق {MONTH_NAMES[jm-1]} {jy} برای همه پرسنل بسته و ثابت شد.')
            return _redirect_period(jy,jm,None,branch_id)

        if action=='reopen_month':
            deleted,_=PayrollSnapshot.objects.filter(month_start=start).delete()
            messages.success(request,f'ماه {MONTH_NAMES[jm-1]} {jy} باز شد ({deleted} رکورد بسته‌شده حذف شد).')
            return _redirect_period(jy,jm,None,branch_id)

    profiles=EmployeeProfile.objects.filter(
        is_active=True,user__is_active=True,
    ).exclude(role='referrer').select_related('user','branch')
    if branch_id.isdigit():
        profiles=profiles.filter(branch_id=int(branch_id))
    profiles=list(profiles.order_by('branch__name','user__last_name','user__first_name','user__username'))

    rows=[_decorate(_payroll_row(profile,start,end)) for profile in profiles]
    total_base=sum((row['base'] for row in rows),ZERO)
    total_commission=sum((row['commission'] for row in rows),ZERO)
    total_bonus=sum((row['bonus']+row['mission'] for row in rows),ZERO)
    total_deductions=sum((row['deductions'] for row in rows),ZERO)
    total_net=sum((row['net'] for row in rows),ZERO)
    total_sales=sum((row['sales'] for row in rows),ZERO)

    selected=None
    if employee_id.isdigit():
        selected=get_object_or_404(
            EmployeeProfile.objects.select_related('user','branch'),
            pk=int(employee_id),is_active=True,user__is_active=True,
        )
    selected_row=_decorate(_payroll_row(selected,start,end)) if selected else None
    history=[]
    cumulative=None
    if selected:
        for offset in range(0,6):
            hy,hm=_previous_month(jy,jm,offset)
            hs,he=_month_bounds(hy,hm)
            hrow=_decorate(_payroll_row(selected,hs,he))
            history.append({
                'jy':hy,'jm':hm,'label':f'{MONTH_NAMES[hm-1]} {hy}',
                'net':hrow['net'],'net_display':hrow['net_display'],
                'commission_display':hrow['commission_display'],'closed':hrow['closed'],
            })
        agg=PayrollMonthlyAdjustment.objects.filter(profile=selected).aggregate(
            bonus=Sum('bonus_toman'),deduction=Sum('salary_deduction_toman'),
            advance=Sum('advance_toman'),insurance=Sum('insurance_toman'),
        )
        cumulative={
            'bonus':_money(agg['bonus'] or 0),'deduction':_money(agg['deduction'] or 0),
            'advance':_money(agg['advance'] or 0),'insurance':_money(agg['insurance'] or 0),
            'absence':Attendance.objects.filter(user=selected.user,status='absent').count(),
            'late':Attendance.objects.filter(user=selected.user,status='late').count(),
        }

    month_options=[]
    for offset in range(0,18):
        oy,om=_previous_month(current_jy,current_jm,offset)
        month_options.append({'jy':oy,'jm':om,'label':f'{MONTH_NAMES[om-1]} {oy}'})

    is_closed=PayrollSnapshot.objects.filter(month_start=start).exists()
    prev_jy,prev_jm=_previous_month(jy,jm,1)
    next_jy,next_jm=(jy+1,1) if jm==12 else (jy,jm+1)

    context={
        'rows':rows,'branches':Branch.objects.filter(is_active=True).order_by('name'),
        'selected_branch':branch_id,'selected':selected,'selected_row':selected_row,
        'history':history,'cumulative':cumulative,'month_options':month_options,
        'jy':jy,'jm':jm,'month_name':MONTH_NAMES[jm-1],'is_closed':is_closed,
        'prev_jy':prev_jy,'prev_jm':prev_jm,'next_jy':next_jy,'next_jm':next_jm,
        'current_jy':current_jy,'current_jm':current_jm,
        'commission_sources':PayrollRule.COMMISSION_SOURCE,
        'summary':{
            'base':_money(total_base),'commission':_money(total_commission),
            'extras':_money(total_bonus),'deductions':_money(total_deductions),
            'net':_money(total_net),'sales':_money(total_sales),'count':len(rows),
        },
    }
    return render(request,'core/payroll_dashboard.html',context)
