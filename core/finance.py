import json, os
from datetime import datetime, time, timedelta
from decimal import Decimal, InvalidOperation
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from django.db.models import Sum, Count
from django.utils import timezone
from django.utils.dateparse import parse_datetime, parse_date
from .models import Branch, FinancialTransaction, IntegrationSyncLog
from .jalali import format_jalali


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
    qs=FinancialTransaction.objects.filter(occurred_at__gte=start,occurred_at__lt=end)
    if branch: qs=qs.filter(branch=branch)
    total=qs.aggregate(v=Sum('amount'))['v'] or Decimal('0')
    by_branch=list(qs.values('branch__name').annotate(total=Sum('amount'),count=Count('id')).order_by('-total'))
    by_payment=list(qs.values('payment_method').annotate(total=Sum('amount'),count=Count('id')).order_by('-total'))
    return {'date':format_jalali(day),'total':total,'count':qs.count(),'by_branch':by_branch,'by_payment':by_payment}
