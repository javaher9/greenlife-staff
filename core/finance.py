import json, os
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from django.db.models import Sum, Count, Q
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from .models import Branch, EmployeeProfile, FinancialTransaction, IntegrationSyncLog, ReferralLead
from .jalali import format_jalali, gregorian_to_jalali, jalali_to_gregorian


def _pick(d, path, default=None):
    cur=d
    for key in (path or '').split('.'):
        if not key: continue
        if isinstance(cur,dict): cur=cur.get(key)
        else: return default
        if cur is None: return default
    return cur

def _rows(payload):
    if isinstance(payload,list): return payload
    for key in ('results','data','items','transactions','revenues'):
        v=payload.get(key) if isinstance(payload,dict) else None
        if isinstance(v,list): return v
        if isinstance(v,dict):
            for sub in ('results','items','data'):
                if isinstance(v.get(sub),list): return v[sub]
    return []

def _dt(value):
    if not value: return None
    if isinstance(value,datetime): x=value
    else:
        s=str(value).replace('Z','+00:00'); x=parse_datetime(s)
        if not x:
            d=parse_date(s[:10]); x=datetime.combine(d,time.min) if d else None
    if x and timezone.is_naive(x): x=timezone.make_aware(x)
    return x

def sync_crm(start=None,end=None):
    started=timezone.now(); base=os.getenv('CRM_BASE_URL','').rstrip('/'); endpoint=os.getenv('CRM_REVENUE_ENDPOINT','/api/revenues/')
    if not base: raise RuntimeError('CRM_BASE_URL تنظیم نشده است')
    params={}
    if start: params[os.getenv('CRM_START_PARAM','start_date')]=str(start)
    if end: params[os.getenv('CRM_END_PARAM','end_date')]=str(end)
    url=base+endpoint+('?' + urlencode(params) if params else '')
    headers={'Accept':'application/json'}; token=os.getenv('CRM_API_TOKEN','')
    if token: headers[os.getenv('CRM_AUTH_HEADER','Authorization')]=os.getenv('CRM_AUTH_PREFIX','Bearer ')+token
    req=Request(url,headers=headers,method='GET')
    created=updated=0
    try:
        with urlopen(req,timeout=int(os.getenv('CRM_TIMEOUT','30'))) as resp: payload=json.loads(resp.read().decode('utf-8'))
        fmap={
            'id':os.getenv('CRM_FIELD_ID','id'),'amount':os.getenv('CRM_FIELD_AMOUNT','amount'),'date':os.getenv('CRM_FIELD_DATE','created_at'),
            'branch':os.getenv('CRM_FIELD_BRANCH','branch.name'),'payment':os.getenv('CRM_FIELD_PAYMENT','payment_method'),
            'service':os.getenv('CRM_FIELD_SERVICE','service'),'patient':os.getenv('CRM_FIELD_PATIENT','patient_id')}
        for row in _rows(payload):
            try: amount=Decimal(str(_pick(row,fmap['amount'],0) or 0))
            except (InvalidOperation,ValueError): continue
            occurred=_dt(_pick(row,fmap['date']));
            if not occurred: continue
            bname=str(_pick(row,fmap['branch'],'') or '').strip(); branch=None
            if bname: branch,_=Branch.objects.get_or_create(name=bname,defaults={'is_active':True})
            ext=str(_pick(row,fmap['id'],'') or '').strip() or None
            defaults={'branch':branch,'occurred_at':occurred,'amount':amount,'payment_method':str(_pick(row,fmap['payment'],'') or ''),'service':str(_pick(row,fmap['service'],'') or ''),'patient_ref':str(_pick(row,fmap['patient'],'') or ''),'raw_data':row}
            if ext:
                obj,was_created=FinancialTransaction.objects.update_or_create(source='crm',external_id=ext,defaults=defaults)
            else:
                obj=FinancialTransaction.objects.create(source='crm',external_id=None,**defaults); was_created=True
            created+=int(was_created); updated+=int(not was_created)
        IntegrationSyncLog.objects.create(provider='crm',status='ok',imported=created,updated=updated,message=f'{len(_rows(payload))} رکورد دریافت شد',started_at=started)
        return {'ok':True,'imported':created,'updated':updated,'received':len(_rows(payload))}
    except Exception as e:
        IntegrationSyncLog.objects.create(provider='crm',status='error',message=str(e)[:2000],started_at=started)
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
