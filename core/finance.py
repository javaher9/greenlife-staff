from hashlib import sha256
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from django.db.models import Sum, Count, Q
from django.utils import timezone
from .models import Branch, EmployeeProfile, FinancialTransaction, IntegrationSyncLog, ReferralLead
from .jalali import format_jalali, gregorian_to_jalali, jalali_to_gregorian
from .integration_api import ApiServerError, call_api


def _crm_date(value):
    raw=str(value or '').strip()
    for pattern in ('%m/%d/%Y','%Y-%m-%d','%Y/%m/%d'):
        try:
            return datetime.strptime(raw,pattern).date()
        except ValueError:
            pass
    return None


def _crm_external_id(row):
    form_value=str(row.get('formValueId') or '').strip()
    group=str(row.get('group') or '').strip()
    if form_value and group:
        return f'glapi:{form_value}:{group}'[:120]
    # Defensive deterministic fallback; never create a fresh duplicate on refresh.
    stable='|'.join(str(row.get(key) or '') for key in (
        'CustomerId','تاریخ فیش پرداختی','مبلغ فیش پرداختی','کلینیک','مشتری',
    ))
    return f'glapi-hash:{sha256(stable.encode("utf-8")).hexdigest()}'


def fetch_crm_finance_payload(*,allow_disabled=False):
    _status,payload=call_api('/crm/finance_month',{},allow_disabled=allow_disabled)
    if not isinstance(payload,dict) or payload.get('success') is not True:
        raise ApiServerError(
            'ساختار پاسخ مالی CRM معتبر نیست.',code='invalid_crm_response',payload=payload,
        )
    rows=payload.get('rows')
    if not isinstance(rows,list):
        raise ApiServerError(
            'فیلد rows در پاسخ مالی CRM وجود ندارد.',code='invalid_crm_rows',payload=payload,
        )
    return payload,rows


def sync_crm(start=None,end=None):
    """Import/upsert documented CRM payment rows from the shared API server."""
    started=timezone.now()
    created=updated=skipped=0
    try:
        payload,rows=fetch_crm_finance_payload()
        today=timezone.localdate()
        current_jy,current_jm,_=gregorian_to_jalali(today.year,today.month,today.day)
        for row in rows:
            if not isinstance(row,dict):
                skipped+=1
                continue
            paid_on=_crm_date(row.get('تاریخ فیش پرداختی'))
            raw_amount=row.get('مبلغ فیش پرداختی')
            if not paid_on or raw_amount in (None,''):
                skipped+=1
                continue
            if start and paid_on<start:
                continue
            if end and paid_on>end:
                continue
            if not start and not end:
                jy,jm,_=gregorian_to_jalali(paid_on.year,paid_on.month,paid_on.day)
                if (jy,jm)!=(current_jy,current_jm):
                    continue
            try:
                amount=Decimal(str(raw_amount).replace(',','').strip())
            except (InvalidOperation,ValueError):
                skipped+=1
                continue
            if amount<=0:
                skipped+=1
                continue
            bname=str(row.get('کلینیک') or '').strip()
            branch=None
            if bname:
                branch,_=Branch.objects.get_or_create(name=bname,defaults={'is_active':True})
            occurred=timezone.make_aware(datetime.combine(paid_on,time.min))
            defaults={
                'branch':branch,
                'occurred_at':occurred,
                'amount':amount,
                'entry_type':'inc',
                'payment_method':str(row.get('نحوه پرداخت فیش') or '').strip(),
                'service':str(row.get('پرداخت خدمات مرتبط') or '').strip(),
                'patient_ref':str(row.get('CustomerId') or '')[:120],
                'person_name':str(row.get('مشتری') or '')[:160],
                'description':'دریافت خودکار از Greenlife API Server',
                'review_status':'approved',
                'raw_data':row,
            }
            _obj,was_created=FinancialTransaction.objects.update_or_create(
                source='crm',external_id=_crm_external_id(row),defaults=defaults,
            )
            created+=int(was_created)
            updated+=int(not was_created)
        message=(
            f'{len(rows)} رکورد دریافت شد؛ {created} جدید، {updated} به‌روزرسانی، '
            f'{skipped} فاقد فیش معتبر'
        )
        IntegrationSyncLog.objects.create(
            provider='crm_api',status='ok',imported=created,updated=updated,
            message=message,started_at=started,
        )
        return {
            'ok':True,'imported':created,'updated':updated,'received':len(rows),
            'skipped':skipped,'reported_count':payload.get('count'),
        }
    except Exception as exc:
        IntegrationSyncLog.objects.create(
            provider='crm_api',status='error',message=str(exc)[:2000],started_at=started,
        )
        raise

def finance_summary(day=None,branch=None):
    day=day or timezone.localdate(); start=timezone.make_aware(datetime.combine(day,time.min)); end=start+timedelta(days=1)
    qs=FinancialTransaction.objects.filter(
        occurred_at__gte=start,occurred_at__lt=end,review_status='approved'
    )
    if branch: qs=qs.filter(branch=branch)
    income=qs.filter(entry_type='inc')
    expenses=qs.filter(entry_type='exp')
    total=income.aggregate(v=Sum('amount'))['v'] or Decimal('0')
    expense_total=expenses.aggregate(v=Sum('amount'))['v'] or Decimal('0')
    by_branch=list(qs.values('branch__name').annotate(
        total=Sum('amount',filter=Q(entry_type='inc')),
        expenses=Sum('amount',filter=Q(entry_type='exp')),
        count=Count('id'),
    ).order_by('-total'))
    for row in by_branch:
        row['total']=row['total'] or Decimal('0')
        row['expenses']=row['expenses'] or Decimal('0')
        row['net']=row['total']-row['expenses']
    by_payment=list(income.values('payment_method').annotate(total=Sum('amount'),count=Count('id')).order_by('-total'))
    return {
        'date':format_jalali(day),'total':total,'expense_total':expense_total,
        'net_total':total-expense_total,'count':qs.count(),
        'income_count':income.count(),'expense_count':expenses.count(),
        'by_branch':by_branch,'by_payment':by_payment,
    }


def flower_sales_summary(day=None,branch=None):
    """Approved manual income attributed to the immutable first appointment owner."""
    day=day or timezone.localdate()
    jy,jm,_=gregorian_to_jalali(day.year,day.month,day.day)
    month_start=timezone.make_aware(datetime.combine(
        datetime(*jalali_to_gregorian(jy,jm,1)).date(),time.min,
    ))
    next_jy,next_jm=(jy+1,1) if jm==12 else (jy,jm+1)
    month_end=timezone.make_aware(datetime.combine(
        datetime(*jalali_to_gregorian(next_jy,next_jm,1)).date(),time.min,
    ))
    year_start=timezone.make_aware(datetime.combine(
        datetime(*jalali_to_gregorian(jy,1,1)).date(),time.min,
    ))
    year_end=timezone.make_aware(datetime.combine(
        datetime(*jalali_to_gregorian(jy+1,1,1)).date(),time.min,
    ))
    day_start=timezone.make_aware(datetime.combine(day,time.min))
    day_end=day_start+timedelta(days=1)

    qs=FinancialTransaction.objects.filter(
        source='manual',entry_type='inc',review_status='approved',
        call_center_owner_id__isnull=False,
    )
    if branch:
        qs=qs.filter(branch=branch)
    rows=list(qs.values(
        'call_center_owner_id','call_center_owner__first_name',
        'call_center_owner__last_name','call_center_owner__username',
    ).annotate(
        today=Sum('amount',filter=Q(occurred_at__gte=day_start,occurred_at__lt=day_end)),
        month=Sum('amount',filter=Q(occurred_at__gte=month_start,occurred_at__lt=month_end)),
        year=Sum('amount',filter=Q(occurred_at__gte=year_start,occurred_at__lt=year_end)),
        sales_count=Count('id',filter=Q(occurred_at__gte=year_start,occurred_at__lt=year_end)),
    ).order_by('-year','-month'))
    zero=Decimal('0')
    existing_ids={row['call_center_owner_id'] for row in rows}
    active_flowers=EmployeeProfile.objects.filter(
        role='call_center',is_active=True,user__is_active=True,
    ).select_related('user')
    for profile in active_flowers:
        if profile.user_id not in existing_ids:
            rows.append({
                'call_center_owner_id':profile.user_id,
                'call_center_owner__first_name':profile.user.first_name,
                'call_center_owner__last_name':profile.user.last_name,
                'call_center_owner__username':profile.user.username,
                'today':zero,'month':zero,'year':zero,'sales_count':0,
            })
    for row in rows:
        row['today']=row['today'] or zero
        row['month']=row['month'] or zero
        row['year']=row['year'] or zero
        full_name=f"{row['call_center_owner__first_name']} {row['call_center_owner__last_name']}".strip()
        row['flower_name']=full_name or row['call_center_owner__username']
    rows.sort(key=lambda row:(row['year'],row['month'],row['today']),reverse=True)
    return {
        'rows':rows,
        'max_today':max((row['today'] for row in rows),default=zero) or Decimal('1'),
        'max_month':max((row['month'] for row in rows),default=zero) or Decimal('1'),
        'max_year':max((row['year'] for row in rows),default=zero) or Decimal('1'),
        'jalali_year':jy,
        'jalali_month':jm,
    }


def finance_visual_analytics(day=None,branch=None):
    """Today/month/year comparisons for branches, services and lead sources."""
    day=day or timezone.localdate()
    jy,jm,_=gregorian_to_jalali(day.year,day.month,day.day)
    start_date=datetime(*jalali_to_gregorian(jy,jm,1)).date()
    next_jy,next_jm=(jy+1,1) if jm==12 else (jy,jm+1)
    end_date=datetime(*jalali_to_gregorian(next_jy,next_jm,1)).date()
    start=timezone.make_aware(datetime.combine(start_date,time.min))
    end=timezone.make_aware(datetime.combine(end_date,time.min))
    year_start=timezone.make_aware(datetime.combine(datetime(*jalali_to_gregorian(jy,1,1)).date(),time.min))
    year_end=timezone.make_aware(datetime.combine(datetime(*jalali_to_gregorian(jy+1,1,1)).date(),time.min))
    day_start=timezone.make_aware(datetime.combine(day,time.min))
    day_end=day_start+timedelta(days=1)
    qs=FinancialTransaction.objects.filter(review_status='approved')
    if branch:
        qs=qs.filter(branch=branch)
    branches=list(qs.values('branch__name').annotate(
        today=Sum('amount',filter=Q(entry_type='inc',occurred_at__gte=day_start,occurred_at__lt=day_end)),
        month=Sum('amount',filter=Q(entry_type='inc',occurred_at__gte=start,occurred_at__lt=end)),
        year=Sum('amount',filter=Q(entry_type='inc',occurred_at__gte=year_start,occurred_at__lt=year_end)),
        expense_month=Sum('amount',filter=Q(entry_type='exp',occurred_at__gte=start,occurred_at__lt=end)),
        count=Count('id',filter=Q(occurred_at__gte=year_start,occurred_at__lt=year_end)),
    ).order_by('-year'))
    zero=Decimal('0')
    for row in branches:
        for key in ('today','month','year','expense_month'):
            row[key]=row[key] or zero
    existing_branch_names={row['branch__name'] for row in branches}
    visible_branches=Branch.objects.filter(is_active=True)
    if branch:
        visible_branches=visible_branches.filter(pk=branch.pk)
    for item in visible_branches:
        if item.name not in existing_branch_names:
            branches.append({'branch__name':item.name,'today':zero,'month':zero,'year':zero,'expense_month':zero,'count':0})
    branches.sort(key=lambda row:(row['year'],row['month']),reverse=True)

    reason_labels=dict(FinancialTransaction.SALE_REASON)
    categories=[]
    for code,label in FinancialTransaction.SALE_REASON:
        values=qs.filter(sale_reason=code).aggregate(
            today=Sum('amount',filter=Q(entry_type='inc',occurred_at__gte=day_start,occurred_at__lt=day_end)),
            month=Sum('amount',filter=Q(entry_type='inc',occurred_at__gte=start,occurred_at__lt=end)),
            year=Sum('amount',filter=Q(entry_type='inc',occurred_at__gte=year_start,occurred_at__lt=year_end)),
            expense_month=Sum('amount',filter=Q(entry_type='exp',occurred_at__gte=start,occurred_at__lt=end)),
            count=Count('id',filter=Q(occurred_at__gte=year_start,occurred_at__lt=year_end)),
        )
        row={'code':code,'label':reason_labels[code],'count':values['count']}
        for key in ('today','month','year','expense_month'):
            row[key]=values[key] or zero
        categories.append(row)
    categories.sort(key=lambda row:(row['year'],row['month']),reverse=True)

    source_labels=dict(ReferralLead.SOURCE)
    sources=[]
    source_codes=list(ReferralLead.SOURCE)+[('direct','مراجعه مستقیم شعبه')]
    for code,label in source_codes:
        source_filter=Q(appointment__lead__source=code) if code!='direct' else Q(appointment__isnull=True)
        values=qs.filter(entry_type='inc').filter(source_filter).aggregate(
            today=Sum('amount',filter=Q(occurred_at__gte=day_start,occurred_at__lt=day_end)),
            month=Sum('amount',filter=Q(occurred_at__gte=start,occurred_at__lt=end)),
            year=Sum('amount',filter=Q(occurred_at__gte=year_start,occurred_at__lt=year_end)),
            count=Count('id',filter=Q(occurred_at__gte=year_start,occurred_at__lt=year_end)),
        )
        row={'code':code,'label':label,'count':values['count']}
        for key in ('today','month','year'):
            row[key]=values[key] or zero
        if row['today'] or row['month'] or row['year'] or row['count']:
            sources.append(row)
    sources.sort(key=lambda row:(row['year'],row['month']),reverse=True)
    return {
        'branches':branches,'categories':categories,'sources':sources,
        'jalali_year':jy,'jalali_month':jm,
    }
