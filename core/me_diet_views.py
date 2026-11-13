"""Authenticated meal reporting and the existing staff request queue; no inferred adherence."""
import json
import uuid
from datetime import date, timedelta
from zoneinfo import ZoneInfo
from django.db import transaction
from django.http import Http404
from django.middleware.csrf import get_token
from django.utils import timezone
from django.views.decorators.http import require_http_methods
from .customer_portal_views import _member, _branches
from .diet_companion_views import _content, plan_data
from .me_sync_views import reply, HEART
from .me_sync_models import MeAccountState, MeDailyAward
from .me_diet_models import MeMealReport
from .me_food_table import CATALOG, food_table
from .models import PatientDietProgram, CustomerPortalMember, CustomerServiceRequest, EmployeeProfile, StaffNotification

REASONS={'unavailable':'مواد این وعده در دسترس نیست','difficult':'اجرای برنامه برایم سخت شده','hunger':'درباره گرسنگی نیاز به راهنمایی دارم','contact':'درخواست تماس درباره رژیم'}
STATUSES=dict(MeMealReport._meta.get_field('status').choices)

def today():
    return timezone.now().astimezone(ZoneInfo('Asia/Tehran')).date()

def plan(member, day):
    program=PatientDietProgram.objects.filter(patient__phone=member.phone,status='active').select_related('patient','catalog_item').order_by('-prescribed_at','-pk').first()
    if program:
        try:
            content=_content(program);days,_=plan_data(content)
            start=timezone.localtime(program.prescribed_at).date()
            if day<start:return program,[], 'این تاریخ پیش از شروع نسخه است.'
            kind=content.presentation_template
            number=1 if kind=='text' else (day.weekday()+2)%7+1 if kind in ('weekly','ramadan') else (day-start).days+1
            current=next((d for d in days if d['number']==number),None)
            cards=[{'key':f'p{program.pk}:{c["key"]}','label':c['label'],'body':c['body']} for c in (current or {}).get('cards',[])]
            return program,cards,'' if cards else 'برای این تاریخ وعده‌ای در نسخه ثبت نشده؛ برای بررسی درخواست کمک بفرست.'
        except Http404:
            return program,[],'محتوای نسخه هنوز آماده نمایش نیست؛ برای پیگیری درخواست کمک بفرست.'
    return None,[{'key':k,'label':label,'body':''} for k,label in [('breakfast','صبحانه'),('lunch','ناهار'),('dinner','شام'),('snacks','میان‌وعده‌ها')]],'نسخهٔ فعالی برای شمارهٔ تو پیدا نشد. این بخش فقط دفتر گزارش توست و برنامهٔ غذایی تجویز نمی‌کند.'

def request_data(r):
    return {'id':r.pk,'status':r.status,'status_label':r.get_status_display(),'note':r.note,'reply':r.staff_note,'created_at':r.created_at.isoformat(),'updated_at':r.updated_at.isoformat()}

def snapshot(request, member, day):
    program,cards,notice=plan(member,day)
    rows={r.meal_key:r for r in MeMealReport.objects.filter(member=member,day=day)}
    for c in cards:
        r=rows.get(c['key']);c['report']={'status':r.status,'note':r.note,'revision':r.revision,'table':r.food_table} if r else None
    done=sum(bool(c['report']) for c in cards)
    return {'authenticated':True,'csrf':get_token(request),'table_version':CATALOG['version'],'day':day.isoformat(),'today':today().isoformat(),'name':member.full_name,'notice':notice,
            'program':{'id':program.pk,'title':program.diet_name,'url':f'/customer/diets/{program.pk}/'} if program else None,
            'meals':cards,'reported':done,'total':len(cards),'percent':round(done/len(cards)*100) if cards else None,
            'hearts':MeDailyAward.objects.filter(member=member).count(),'awarded_today':MeDailyAward.objects.filter(member=member,day=day).exists(),
            'branches':[{'id':b.pk,'name':b.name} for b in _branches()],
            'requests':[request_data(r) for r in member.requests.filter(kind='diet').order_by('-created_at')[:8]]}

@require_http_methods(['GET','POST'])
def diet(request):
    member=_member(request)
    if not member:return reply({'authenticated':False},401)
    data={}
    try:
        if request.method=='POST':
            if request.content_type!='application/json' or len(request.body)>6000:raise ValueError()
            data=json.loads(request.body)
            if not isinstance(data,dict):raise ValueError()
        day=date.fromisoformat(data.get('day') or request.GET.get('day') or today().isoformat())
        if not today()-timedelta(days=6)<=day<=today():raise ValueError()
    except (ValueError,TypeError):return reply({'error':'روز یا اطلاعات درخواست معتبر نیست.'},400)
    if request.method=='GET':return reply(snapshot(request,member,day))
    with transaction.atomic():
        member=CustomerPortalMember.objects.select_for_update().get(pk=member.pk)
        program,cards,_=plan(member,day)
        action=data.get('action')
        if action=='meal':
            card=next((c for c in cards if c['key']==data.get('key')),None)
            status=data.get('status');note=data.get('note','');revision=data.get('revision',0)
            if not card or not isinstance(status,str) or status not in STATUSES or not isinstance(note,str) or len(note)>200 or type(revision) is not int:return reply({'error':'گزارش وعده معتبر نیست.'},400)
            row=MeMealReport.objects.filter(member=member,day=day,meal_key=card['key']).first()
            if revision!=(row.revision if row else 0):return reply({'error':'این وعده در دستگاه دیگری تغییر کرده؛ ابتدا تازه‌سازی کن.'},409)
            table=row.food_table if row else {}
            if 'table' in data:
                if day!=today():return reply({'error':'روز عوض شده؛ وعده‌های امروز را تازه‌سازی کن.'},409)
                if data.get('consumed') is not True or status=='skipped':return reply({'error':'فقط میز مصرف‌شده را به‌عنوان وعده ثبت کن.'},400)
                try:table=food_table(data['table'])
                except ValueError as exc:return reply({'error':str(exc)},400)
            if status=='skipped':table={}
            MeMealReport.objects.update_or_create(member=member,day=day,meal_key=card['key'],defaults={'label':card['label'][:200],'status':status,'note':note.strip(),'revision':revision+1,'food_table':table})
            count=MeMealReport.objects.filter(member=member,day=day,meal_key__in=[c['key'] for c in cards]).count()
            if cards and count==len(cards):
                # One daily award across ALL routes; every honest status counts equally.
                award,created=MeDailyAward.objects.get_or_create(member=member,day=day)
                if created:
                    state,_=MeAccountState.objects.get_or_create(member=member)
                    values=state.values or {};heart=values.get(HEART) or {'version':1,'days':{},'awards':{}}
                    heart['startedAt']=heart.get('startedAt') or timezone.now().isoformat()
                    heart['awards']={str(a.day):a.granted_at.isoformat() for a in member.me_awards.all()};values[HEART]=heart
                    state.values=values;state.version+=1;state.save()
        elif action=='help':
            reason=data.get('reason');note=data.get('note','');name=data.get('name','');label=''
            try:token=uuid.UUID(str(data.get('token','')))
            except (ValueError,TypeError):return reply({'error':'شناسه ارسال معتبر نیست.'},400)
            previous=member.requests.filter(request_token=token).first()
            if previous:return reply({**snapshot(request,member,day),'sent':request_data(previous)})
            if CustomerServiceRequest.objects.filter(request_token=token).exists():return reply({'error':'شناسه تکراری است.'},409)
            if not isinstance(reason,str) or reason not in REASONS or not isinstance(note,str) or len(note)>180 or not isinstance(name,str) or not 3<=len(name.strip())<=140 or data.get('consent') is not True:return reply({'error':'نام، موضوع و رضایت ارسال را کامل کن.'},400)
            branch=_branches().filter(pk=data.get('branch') if type(data.get('branch')) is int else -1).first()
            if not branch:return reply({'error':'شعبه را انتخاب کن.'},400)
            if data.get('key'):
                card=next((c for c in cards if c['key']==data['key']),None)
                if not card:return reply({'error':'وعده معتبر نیست.'},400)
                label=card['label'][:45]
            active=member.requests.filter(kind='diet',status__in=('pending','contacted')).first()
            if active:return reply({**snapshot(request,member,day),'sent':request_data(active),'existing':True})
            if member.requests.filter(kind='diet',created_at__gte=timezone.now()-timedelta(days=1)).count()>=5:return reply({'error':'چند درخواست امروز ثبت شده؛ برای پیگیری با مرکز تماس بگیر.'},429)
            member.full_name=name.strip();member.save(update_fields=['full_name'])
            text=f'{REASONS[reason]} | {day} {label}\n{note.strip()}'[:300]
            row=CustomerServiceRequest.objects.create(member=member,kind='diet',branch=branch,note=text,request_token=token)
            staff=EmployeeProfile.objects.filter(is_active=True,user__is_active=True,role__in=('call_center','admin','internal_manager')).select_related('user')
            StaffNotification.objects.bulk_create([StaffNotification(user=p.user,title='درخواست کمک رژیم از گرین‌لایف من',message=f'درخواست #{row.pk} | {branch.name} | برای بررسی، صف درخواست‌های مشتریان را باز کنید.',notification_type='info') for p in staff])
            return reply({**snapshot(request,member,day),'sent':request_data(row)})
        else:return reply({'error':'عملیات معتبر نیست.'},400)
    return reply(snapshot(request,member,day))
