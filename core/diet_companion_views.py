"""Verified patient diets and self-reporting. Staff preview never writes patient data."""
import hashlib
import json
import uuid
from django.db import transaction
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404,render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_GET,require_POST
from .customer_portal_views import _require_member
from .models import CustomerPortalMember,PatientDietProgram,TreatmentRichContent,DietMealCheckin,DietFoodChange
from .treatment_content_views import _content_for_preview
from .diet_week_plan import build_orange_week,DAYS
from .diet_thirteen_plan import build_thirteen_days
from .diet_ramadan_plan import build_ramadan_week
from .diet_meal_icons import meal_illustration_url
from .diet_extras_display import prepare_diet_extras
from .diet_template_views import _deduplicate


def plan_data(content):
    sections=list(content.sections.prefetch_related('media').all())
    kind=content.presentation_template
    unassigned=[]
    if kind=='thirteen':
        raw,unassigned=build_thirteen_days(sections,infer_first_keto_day=content.master_item.name=='Keto-Fast')
        labels=[f'روز {i}' for i in range(1,14)]
    elif kind=='weekly':raw=build_orange_week(sections);labels=DAYS
    elif kind=='ramadan':raw=build_ramadan_week(sections);labels=DAYS
    elif kind=='text':
        raw={1:[{'slot':'other','label':s.title,'body':s.body,'photo':next((m.url for m in s.media.all() if m.kind=='image' and m.url),'')} for s in sections if s.body.strip()]};labels=['برنامه امروز']
    else:raise Http404('این برنامه هنوز برای اجرای شخصی آماده نیست.')
    result=[]
    for n,label in enumerate(labels,1):
        cards=[]
        for card in _deduplicate(raw.get(n,[])):
            if not card.get('body','').strip():continue
            c=dict(card)
            c['label']=c.get('label') or c.get('title') or 'برنامه غذایی'
            c['key']=hashlib.sha256((str(n)+'|'+c.get('slot','')+'|'+c['body']).encode()).hexdigest()[:32]
            c['icon']=meal_illustration_url(c.get('slot','other'))
            cards.append(c)
        result.append({'number':n,'label':label,'cards':cards})
    extras=prepare_diet_extras(sections,quota_text=content.quota_text,free_foods_text=content.free_foods_text,notes_text=content.diet_notes_text)
    extras+= [{'title':s.title,'body':s.body} for s in unassigned]
    return result,extras


def _content(program):
    qs=TreatmentRichContent.objects.select_related('master_item').filter(is_active=True,master_item__category='diet')
    if program.catalog_item_id:return get_object_or_404(qs,master_item_id=program.catalog_item_id)
    matches=list(qs.filter(master_item__branch__isnull=True,master_item__name=program.diet_name)[:2])
    if len(matches)!=1:raise Http404('محتوای تأییدشده این نسخه هنوز آماده نیست؛ با مرکز هماهنگ کنید.')
    return matches[0]


def _owned(request,pk):
    member=_require_member(request)
    if not isinstance(member,CustomerPortalMember):return None,member
    # Verified phone AND prescription ownership, never a caller-supplied patient ID.
    program=get_object_or_404(PatientDietProgram.objects.select_related('patient','catalog_item'),pk=pk,patient__phone=member.phone)
    return program,None


def _cycle(program,content):
    if content.presentation_template in ('weekly','ramadan','text'):
        span=1 if content.presentation_template=='text' else 7
        return max(0,(timezone.localdate()-timezone.localtime(program.prescribed_at).date()).days//span)
    return 0


def _state(program,content,days):
    cycle=_cycle(program,content)
    rows=list(program.meal_checkins.filter(cycle=cycle))
    valid={(d['number'],c['key']) for d in days for c in d['cards']}
    rows=[r for r in rows if (r.day,r.meal_key) in valid]
    done={(r.day,r.meal_key) for r in rows}
    completed=[d['number'] for d in days if d['cards'] and all((d['number'],c['key']) in done for c in d['cards'])]
    badges=[]
    if program.meal_checkins.exists():badges.append('🌱 اولین ثبت')
    if len(completed)>=3:badges.append('🌿 سه روز پیگیری')
    eligible=[d for d in days if d['cards']]
    if eligible and len(eligible)==len(days) and len(completed)==len(days):badges.append('🌳 ثبت کامل برنامه')
    recent=[{'food':c.food,'amount':c.amount,'reason':c.get_reason_display(),'day':c.day} for c in program.food_changes.order_by('-created_at')[:8]]
    return {'records':[{'day':r.day,'key':r.meal_key,'status':r.status,'note':r.note} for r in rows], 'completed_days':completed,'badges':badges,'changes':recent,'cycle':cycle}


@require_GET
def customer_diets(request):
    member=_require_member(request)
    if not isinstance(member,CustomerPortalMember):return member
    programs=PatientDietProgram.objects.filter(patient__phone=member.phone).select_related('patient').order_by('-prescribed_at')
    response=render(request,'core/customer_portal/diets.html',{'programs':programs})
    response['Cache-Control']='private, no-store'
    return response


def _render(request,content,program=None):
    days,extras=plan_data(content)
    if not any(d['cards'] for d in days):raise Http404('این برنامه هنوز محتوا ندارد.')
    initial=_state(program,content,days) if program else {'records':[],'completed_days':[],'badges':[],'changes':[]}
    audio={r.day_number:r.url for r in content.daily_audio.all() if r.url}
    for day in days:day['audio']=audio.get(day['number']) or content.audio_url
    response=render(request,'core/diet_companion.html',{'content':content,'program':program,'days':days,'extras':extras,'initial':initial,'demo':program is None,'can_record':program is None or program.status=='active','endpoint':reverse('customer_diet_log',args=[program.pk]) if program else '', 'title':content.display_title or content.master_item.name})
    response['Cache-Control']='private, no-store'
    return response


@require_GET
def customer_diet(request,pk):
    program,error=_owned(request,pk)
    if error:return error
    return _render(request,_content(program),program)


@require_GET
def companion_preview(request,item_id):
    if not request.user.is_authenticated:
        from django.contrib.auth.views import redirect_to_login
        return redirect_to_login(request.get_full_path())
    return _render(request,_content_for_preview(request,item_id))


@require_POST
def customer_diet_log(request,pk):
    program,error=_owned(request,pk)
    if error:return error
    if program.status!='active':return JsonResponse({'error':'این دوره فعال نیست.'},status=409)
    if len(request.body)>10000:return JsonResponse({'error':'اطلاعات بیش از حد مجاز است.'},status=400)
    content=_content(program);days,_=plan_data(content)
    try:
        data=json.loads(request.body)
        if not isinstance(data,dict):raise ValueError()
        day=int(data.get('day',0));selected=next(d for d in days if d['number']==day)
        cycle=_cycle(program,content)
        with transaction.atomic():
            # Serialize concurrent devices for this exact prescription.
            locked=PatientDietProgram.objects.select_for_update().get(pk=program.pk)
            if locked.status!='active':return JsonResponse({'error':'این دوره فعال نیست.'},status=409)
            if data.get('action')=='meal':
                card=next(c for c in selected['cards'] if c['key']==data.get('key'))
                status=data.get('status','')
                if status not in dict(DietMealCheckin.STATUS) and status!='':raise ValueError()
                target=dict(program=program,cycle=cycle,day=day,meal_key=card['key'])
                if not status:DietMealCheckin.objects.filter(**target).delete()
                else:
                    note=data.get('note','')
                    if not isinstance(note,str) or len(note)>600:raise ValueError()
                    DietMealCheckin.objects.update_or_create(**target,defaults={'status':status,'meal_label':card['label'][:200],'note':note,'reported_on':timezone.localdate()})
            elif data.get('action')=='change':
                food=data.get('food','');amount=data.get('amount','');reason=data.get('reason','')
                if not isinstance(food,str) or not food.strip() or len(food)>400 or not isinstance(amount,str) or len(amount)>120:raise ValueError()
                if reason not in ('','hunger','craving','party','stress','other'):raise ValueError()
                request_id=uuid.UUID(str(data.get('request_id','')))
                DietFoodChange.objects.get_or_create(program=program,request_id=request_id,defaults={'day':day,'food':food.strip(),'amount':amount.strip(),'reason':reason})
            else:raise ValueError()
    except (ValueError,TypeError,StopIteration, json.JSONDecodeError):
        return JsonResponse({'error':'اطلاعات وعده یا روز معتبر نیست.'},status=400)
    return JsonResponse(_state(program,content,days))
