from datetime import datetime, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import Attendance, LeaveRequest, ReferralLead, StaffNotification
from .operations import shift_rule


def _call_center_is_on_duty(user, now=None):
    now=timezone.localtime(now or timezone.now())
    day=now.date()
    if LeaveRequest.objects.filter(
        user=user,status='approved',start_date__lte=day,end_date__gte=day
    ).exists():
        return False
    attendance=Attendance.objects.filter(
        user=user,date=day,check_in__isnull=False,check_out__isnull=True
    ).first()
    if not attendance:
        return False
    rule=shift_rule(user,day)
    end=rule.get('end')
    if end:
        end_dt=timezone.make_aware(datetime.combine(day,end),timezone.get_current_timezone())
        if now>end_dt+timedelta(minutes=15):
            return False
    return True


def _lead_delay_alerts_for_user(user, now=None):
    """Create at most one reminder/warning per lead and delay threshold."""
    now=timezone.localtime(now or timezone.now())
    if not _call_center_is_on_duty(user,now):
        return {'created':0,'urgent':0,'latest_message':''}
    profile=getattr(user,'profile',None)
    if not profile or profile.role!='call_center' or not profile.is_active:
        return {'created':0,'urgent':0,'latest_message':''}

    threshold_30=now-timedelta(minutes=30)
    qs=(
        ReferralLead.objects
        .filter(assigned_to=profile,status='new')
        .filter(Q(contact_result='')|Q(contact_result__isnull=True))
        .filter(
            Q(assigned_at__lte=threshold_30) |
            Q(assigned_at__isnull=True,created_at__lte=threshold_30)
        )
        .order_by('assigned_at','created_at','id')
    )
    created=0
    urgent=0
    latest=''
    today=now.date()
    for lead in qs[:80]:
        started=lead.assigned_at or lead.created_at
        age_minutes=max(0,int((now-started).total_seconds()//60))
        if age_minutes>=60:
            notification_type='lead_delay_60'
            title='⚠ تأخیر در تماس با لید'
            message=f'لید «{lead.full_name}» با شماره {lead.phone} حدود {age_minutes} دقیقه است به شما تخصیص داده شده و هنوز نتیجه تماس ثبت نشده است. لطفاً همین حالا پیگیری کنید. (کد {lead.pk})'
            urgent+=1
        else:
            notification_type='lead_delay_30'
            title='یادآوری تماس با لید'
            message=f'لید «{lead.full_name}» با شماره {lead.phone} حدود {age_minutes} دقیقه است منتظر تماس شماست. لطفاً پیگیری و نتیجه را ثبت کنید. (کد {lead.pk})'
        exists=StaffNotification.objects.filter(
            user=user,
            notification_type=notification_type,
            related_date=today,
            message=message,
        ).exists()
        if exists:
            continue
        StaffNotification.objects.create(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            related_date=today,
        )
        created+=1
        latest=message
    return {'created':created,'urgent':urgent,'latest_message':latest}


@login_required
@require_POST
def check_lead_delay_alerts(request):
    profile=getattr(request.user,'profile',None)
    if not profile or profile.role!='call_center' or not profile.is_active:
        return JsonResponse({'ok':False,'error':'forbidden'},status=403)
    result=_lead_delay_alerts_for_user(request.user)
    return JsonResponse({'ok':True,**result})


@login_required
@require_POST
def mark_call_started(request, pk):
    """Record a call attempt without inventing a contact outcome.

    A dial/call click is not a result. The lead status changes only after the
    operator records an actual outcome, so management never sees "contacted"
    with an empty contact_result.
    """
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'call_center' or not profile.is_active:
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    lead = get_object_or_404(ReferralLead, pk=pk, assigned_to=profile)
    changed = False

    labels = {
        'new': 'جدید',
        'contacted': 'تماس گرفته شد',
        'appointment': 'نوبت داده شد',
        'visited': 'مراجعه کرد',
        'won': 'فروش موفق',
        'lost': 'تمایل به پیگیری ندارد',
    }
    return JsonResponse({
        'ok': True,
        'changed': changed,
        'status': lead.status,
        'label': labels.get(lead.status, lead.get_status_display()),
        'needs_result': not bool(lead.contact_result),
    })


@login_required
@require_POST
def save_call_result(request, pk):
    """Persist simple call outcomes directly from the call-center work queue."""
    profile=getattr(request.user,'profile',None)
    if not profile or profile.role!='call_center' or not profile.is_active:
        return JsonResponse({'ok':False,'error':'forbidden'},status=403)
    lead=get_object_or_404(ReferralLead,pk=pk,assigned_to=profile)
    result=(request.POST.get('result') or '').strip()
    if result not in ('no_answer','not_interested'):
        return JsonResponse({'ok':False,'error':'invalid_result'},status=400)
    lead.contact_result=result
    lead.status='contacted' if result=='no_answer' else 'lost'
    lead.next_follow_up=None
    lead.save(update_fields=['contact_result','status','next_follow_up','updated_at'])
    return JsonResponse({
        'ok':True,
        'result':result,
        'result_label':lead.get_contact_result_display(),
        'status':lead.status,
        'label':lead.get_status_display(),
    })


_CALL_CENTER_STAFF_STYLE = r'''<style id="greenlife-call-center-staff-ui-v8">
/* Staff-only call-center readability + wide-screen workspace. */
@media (min-width: 1180px){
  .cc-v5{max-width:1880px!important;width:100%!important;gap:14px!important}
  .cc-v5-stage{grid-template-columns:minmax(0,1fr) 340px!important;gap:14px!important}
  .cc-v5-patient{grid-template-columns:minmax(300px,1.55fr) minmax(120px,.72fr) 110px 128px 220px!important;gap:12px!important;padding:12px 14px!important}
  .cc-v5-hero{grid-template-columns:minmax(0,1.6fr) minmax(350px,.72fr)!important;padding:20px 24px!important}
  .cc-v5-toolbar{grid-template-columns:minmax(380px,1fr) 170px auto!important;padding:10px!important}
  .cc-v5-side{top:74px!important}
}

/* Raise contrast on the white theme. */
.cc-v5{--muted:#59677a!important;color:#1f2d43!important}
.cc-v5 p,.cc-v5 small{color:#59677a!important}
.cc-v5-kpi small{color:rgba(255,255,255,.92)!important}
.cc-v5 .cc-v5-hero p,
.cc-v5 .cc-v5-motto small,
.cc-v5 .cc-v6-flow-step small,
.cc-v5 .cc-v7-performance-head p,
.cc-v5 .cc-v7-metric small,
.cc-v5 .cc-v5-group-label small,
.cc-v5 .cc-v5-section-head p{color:#526176!important}
.cc-v5 .cc-v5-section-head a{color:#5f3f8d!important}
.cc-v5 .cc-v6-flow-step strong,
.cc-v5 .cc-v7-metric span,
.cc-v5 .cc-v7-funnel-step span{color:#4b5b70!important}

/* Font sizes on desktop were too small for the operators' wide monitors. */
.cc-v5 p{font-size:11px!important;line-height:1.85!important}
.cc-v5 small{font-size:10px!important;line-height:1.7!important}
.cc-v5 label,.cc-v5 input,.cc-v5 select,.cc-v5 textarea{font-size:11px!important}
.cc-v5 .cc-v5-eyebrow{font-size:10px!important}
.cc-v5 .cc-v5-hero h1{font-size:25px!important}
.cc-v5 .cc-v5-motto strong{font-size:12px!important}
.cc-v5 .cc-v6-flow-step strong{font-size:10px!important}
.cc-v5 .cc-v5-kpi-label{font-size:11px!important}
.cc-v5 .cc-v5-kpi strong{font-size:32px!important}
.cc-v5 .cc-v7-performance-head h2{font-size:14px!important}
.cc-v5 .cc-v7-period{font-size:10px!important;padding:7px 11px!important}
.cc-v5 .cc-v7-metric span{font-size:10px!important}
.cc-v5 .cc-v7-metric strong{font-size:23px!important}
.cc-v5 .cc-v7-funnel-step span{font-size:9px!important}
.cc-v5 .cc-v7-funnel-step b{font-size:16px!important}
.cc-v5 .cc-v5-action{height:48px!important;font-size:11px!important}
.cc-v5 .cc-v5-count{font-size:9px!important;min-width:20px!important;height:20px!important}
.cc-v5 .cc-v5-search input,.cc-v5 .cc-v5-select{height:42px!important;font-size:11px!important}
.cc-v5 .cc-v5-quick button{height:36px!important;font:900 10px Tahoma!important}
.cc-v5 .cc-v5-group-label strong{font-size:11px!important}
.cc-v5 .cc-v5-chip{font-size:10px!important;padding:7px 10px!important}
.cc-v5 .cc-v5-chip b{font-size:9px!important}
.cc-v5 .cc-v5-group-new input{height:38px!important;font-size:10px!important}
.cc-v5 .cc-v5-group-new button{height:38px!important;font:900 10px Tahoma!important}
.cc-v5 .cc-v5-lead-new input,.cc-v5 .cc-v5-lead-new select{height:42px!important;font:800 11px Tahoma!important}
.cc-v5 .cc-v5-lead-new button{height:42px!important;font:900 11px Tahoma!important}
.cc-v5 .cc-v5-section-head h2,.cc-v5 .cc-v5-section-head h3{font-size:14px!important}
.cc-v5 .cc-v5-section-head a{font-size:10px!important}
.cc-v5 .cc-v5-patient{min-height:76px!important}
.cc-v5 .cc-v5-person-avatar{width:54px!important;height:54px!important}
.cc-v5 .cc-v5-person{grid-template-columns:54px minmax(0,1fr)!important}
.cc-v5 .cc-v5-status{font-size:10px!important;padding:7px 9px!important}
.cc-v5 .cc-v5-row-actions{flex-wrap:wrap!important;align-items:center!important;row-gap:5px!important}
.cc-v5 .cc-v5-row-actions a,.cc-v5 .cc-v5-row-actions button{font-size:10px!important;min-height:35px!important}
.cc-v5 .cc-v5-open{font-size:10px!important}

/* Make the working list visually dominant. */
.cc-v5-work-queue-card{border-color:#dce9e3!important;box-shadow:0 12px 34px rgba(31,91,65,.07)!important}
.cc-v5-work-queue-card>.cc-v5-section-head{background:linear-gradient(90deg,#f3faf6,#fff)!important;border-radius:18px 18px 0 0}
.cc-v5-work-queue-card>.cc-v5-section-head h2{color:#1f684b!important}
.cc-v5-patient.cc-priority-new{border-color:#d7eade!important;background:#fbfffd!important}
.cc-priority-pill{display:inline-flex;align-items:center;margin-top:5px;margin-inline-start:6px;padding:4px 7px;border-radius:999px;background:#eaf8f1;color:#247a58!important;font:900 9px Tahoma!important;white-space:nowrap}
.cc-whatsapp-action{display:inline-flex;align-items:center;justify-content:center;padding:7px 9px;border:1px solid #d5e9df;border-radius:9px;background:#f2fbf6;color:#247a58!important;font:900 10px Tahoma!important;white-space:nowrap;text-decoration:none!important}
.cc-result-action{background:#f3eef9!important;color:#64448f!important;border-color:#dfd4ec!important}
.cc-result-strip{grid-column:1/-1;display:grid;grid-template-columns:auto repeat(4,minmax(0,1fr));gap:6px;align-items:center;margin-top:6px;padding:8px;border:1px solid #e5d8f2;border-radius:11px;background:#faf7fd}
.cc-result-strip strong{font-size:9px;color:#674795;white-space:nowrap}.cc-result-strip button,.cc-result-strip a{min-height:32px!important;display:flex!important;align-items:center!important;justify-content:center!important;border:1px solid #dfe5ec!important;border-radius:8px!important;background:#fff!important;color:#425067!important;font:900 9px Tahoma!important;text-decoration:none!important;cursor:pointer}.cc-result-strip .danger{background:#fff3f5!important;color:#a23b55!important;border-color:#f0d8de!important}.cc-result-strip .good{background:#eef9f3!important;color:#277654!important;border-color:#d4ebdf!important}
@media(max-width:900px){.cc-result-strip{grid-template-columns:1fr 1fr}.cc-result-strip strong{grid-column:1/-1}}

@media (max-width: 1179px){
  .cc-v5 p{font-size:10px!important}
  .cc-v5 small{font-size:9px!important}
  .cc-v5 .cc-v5-action{font-size:10px!important}
}
</style>'''


_CALL_TRACKING_SCRIPT = r'''<script>
(function(){
  if(window.__greenlifeCallTrackingInstalled)return;
  window.__greenlifeCallTrackingInstalled=true;

  function csrfToken(){
    var input=document.querySelector('input[name="csrfmiddlewaretoken"]');
    if(input&&input.value)return input.value;
    var names=['csrftoken','greenlife_lan_csrftoken'];
    for(var i=0;i<names.length;i++){
      var m=document.cookie.match(new RegExp('(?:^|;\\s*)'+names[i]+'=([^;]+)'));
      if(m)return decodeURIComponent(m[1]);
    }
    return '';
  }

  function leadIdFor(node){
    var row=node&&node.closest?node.closest('.cc-v5-patient'):null;
    if(row){
      var open=row.querySelector('a.cc-v5-open[href*="/call-center/leads/"]');
      if(open){
        var rm=(open.getAttribute('href')||'').match(/\/call-center\/leads\/(\d+)\//);
        if(rm)return rm[1];
      }
    }
    var pm=location.pathname.match(/^\/call-center\/leads\/(\d+)\//);
    return pm?pm[1]:null;
  }

  function normalizeIranMobile(value){
    var digits=String(value||'').replace(/\D/g,'');
    if(digits.indexOf('0098')===0)digits=digits.slice(4);
    if(digits.indexOf('98')===0)digits=digits.slice(2);
    if(digits.indexOf('0')===0)digits=digits.slice(1);
    return digits.length===10&&digits.indexOf('9')===0?'98'+digits:'';
  }

  function updateRow(row,label){
    if(!row)return;
    var badge=row.querySelector('.cc-v5-status');
    if(badge&&label)badge.textContent=label;
    var done=row.querySelector('.cc-contact-done');
    if(done){
      done.textContent='ثبت نتیجه تماس';
      done.disabled=false;
      done.removeAttribute('aria-disabled');
      done.style.opacity='1';
      done.style.cursor='pointer';
    }
  }

  function resultStrip(row,leadId){
    if(!row)return;
    var old=row.querySelector('.cc-result-strip');if(old)return old;
    var strip=document.createElement('div');strip.className='cc-result-strip';
    strip.innerHTML='<strong>نتیجه تماس را ثبت کن:</strong>'+
      '<button type="button" data-result="no_answer">پاسخ نداد</button>'+
      '<a href="/call-center/leads/'+leadId+'/">نیاز به پیگیری</a>'+
      '<a class="good" href="/call-center/leads/'+leadId+'/appointment/">ثبت نوبت</a>'+
      '<button type="button" class="danger" data-result="not_interested">تمایل ندارد</button>';
    row.appendChild(strip);
    strip.querySelectorAll('button[data-result]').forEach(function(btn){
      btn.addEventListener('click',function(){
        var body=new FormData(),token=csrfToken();if(token)body.append('csrfmiddlewaretoken',token);body.append('result',btn.dataset.result);
        btn.disabled=true;btn.textContent='در حال ثبت...';
        fetch('/call-center/leads/'+leadId+'/result/',{method:'POST',body:body,credentials:'same-origin',headers:{'X-Requested-With':'XMLHttpRequest'}})
          .then(function(r){if(!r.ok)throw new Error();return r.json()})
          .then(function(data){if(data&&data.ok){updateRow(row,data.label);strip.innerHTML='<strong>✓ نتیجه ثبت شد: '+data.result_label+'</strong>';row.classList.remove('cc-priority-new');var p=row.querySelector('.cc-priority-pill');if(p)p.remove()}})
          .catch(function(){btn.disabled=false;btn.textContent='دوباره ثبت کن'});
      });
    });
    return strip;
  }

  function postContact(leadId,row,options){
    options=options||{};
    var token=csrfToken();
    var body=new FormData();
    if(token)body.append('csrfmiddlewaretoken',token);
    var endpoint='/call-center/leads/'+leadId+'/call-started/';

    if(options.optimistic)updateRow(row,'تماس گرفته شد');

    return fetch(endpoint,{
      method:'POST',body:body,credentials:'same-origin',keepalive:true,
      headers:{'X-Requested-With':'XMLHttpRequest'}
    }).then(function(response){
      if(!response.ok)throw new Error('contact status '+response.status);
      return response.json();
    }).then(function(data){
      if(data&&data.ok){
        updateRow(row,data.label||'');
        if(data.needs_result)resultStrip(row,leadId);
      }
      return data;
    }).catch(function(){
      if(options.button){
        options.button.textContent='دوباره ثبت کن';
        options.button.disabled=false;
        options.button.removeAttribute('aria-disabled');
        options.button.style.opacity='1';
        options.button.style.cursor='pointer';
      }
      return null;
    });
  }

  function markWorkQueue(){
    var patients=document.querySelector('.cc-v5-patients');
    if(!patients)return;
    var card=patients.closest('.cc-v5-card');
    if(!card)return;
    card.classList.add('cc-v5-work-queue-card');
    var head=card.querySelector('.cc-v5-section-head');
    if(!head)return;
    var title=head.querySelector('h2,h3');
    if(title)title.textContent='صف کار امروز';
    var copy=head.querySelector('p');
    if(copy)copy.textContent='از لیدهای نیازمند پیگیری شروع کن؛ نتیجه هر تماس را همان لحظه ثبت کن.';
  }

  function enhanceDashboard(){
    if(location.pathname!='/call-center/'&&location.pathname!='/call-center')return;

    markWorkQueue();

    var actions=document.querySelectorAll('a.cc-v5-action[href*="status=contacted"]');
    for(var i=0;i<actions.length;i++){
      var text=(actions[i].textContent||'').trim();
      if(text.indexOf('ثبت نتیجه تماس')!==-1){
        actions[i].textContent='✓ تماس گرفته شد';
      }
    }

    var rows=document.querySelectorAll('.cc-v5-patient');
    for(var j=0;j<rows.length;j++){
      var row=rows[j];
      var actionsBox=row.querySelector('.cc-v5-row-actions');
      var open=row.querySelector('a.cc-v5-open[href*="/call-center/leads/"]');
      if(!actionsBox||!open)continue;
      var match=(open.getAttribute('href')||'').match(/\/call-center\/leads\/(\d+)\//);
      if(!match)continue;

      open.classList.add('cc-result-action');
      if((open.textContent||'').trim().length<18)open.textContent='نتیجه / نوبت';

      var tel=row.querySelector('a[href^="tel:"]');
      if(!tel){var raw=(row.textContent||'').match(/(?:\+98|0098|98|0)?9\d{9}/);if(raw)tel={getAttribute:function(){return raw[0];}};}
      if(tel&&!actionsBox.querySelector('.cc-whatsapp-action')){
        var mobile=normalizeIranMobile(tel.getAttribute('href')||tel.textContent||'');
        if(mobile){
          var whatsapp=document.createElement('a');
          whatsapp.className='cc-whatsapp-action';
          whatsapp.href='https://wa.me/'+mobile;
          whatsapp.target='_blank';
          whatsapp.rel='noopener';
          whatsapp.textContent='واتساپ';
          actionsBox.appendChild(whatsapp);
        }
      }

      var badge=row.querySelector('.cc-v5-status');
      if(!badge||badge.textContent.trim()!=='جدید')continue;
      row.classList.add('cc-priority-new');
      var personCopy=row.querySelector('.cc-v5-person-copy');
      if(personCopy&&!row.querySelector('.cc-priority-pill')){
        var pill=document.createElement('span');
        pill.className='cc-priority-pill';
        pill.textContent='اولویت تماس';
        personCopy.appendChild(pill);
      }
      if(actionsBox.querySelector('.cc-contact-done'))continue;

      var button=document.createElement('button');
      button.type='button';
      button.className='cc-contact-done';
      button.dataset.leadId=match[1];
      button.textContent='ثبت نتیجه تماس';
      button.style.cssText='cursor:pointer;white-space:nowrap';
      actionsBox.appendChild(button);
    }
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',enhanceDashboard);
  }else{
    enhanceDashboard();
  }

  document.addEventListener('click',function(event){
    var explicit=event.target.closest('.cc-contact-done');
    if(explicit){
      event.preventDefault();
      if(explicit.disabled)return;
      var row=explicit.closest('.cc-v5-patient');
      var leadId=explicit.dataset.leadId||leadIdFor(explicit);
      if(!leadId)return;
      explicit.disabled=true;
      explicit.textContent='در حال ثبت...';
      postContact(leadId,row,{button:explicit});
      return;
    }

    var link=event.target.closest('a[href^="tel:"]');
    if(!link||location.pathname.indexOf('/call-center/')!==0)return;
    var leadId=leadIdFor(link);
    if(!leadId)return;
    var row=link.closest('.cc-v5-patient');
    postContact(leadId,row,{optimistic:true});
  },true);
})();
</script>'''


class CallCenterCallTrackingMiddleware:
    """Inject staff-only call tracking and readability UI on call-center pages."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        user = getattr(request, 'user', None)
        profile = getattr(user, 'profile', None) if getattr(user, 'is_authenticated', False) else None
        if (
            not profile
            or profile.role != 'call_center'
            or not request.path.startswith('/call-center/')
            or response.status_code != 200
            or response.streaming
            or not str(response.get('Content-Type', '')).startswith('text/html')
        ):
            return response

        content = response.content
        marker = b'</body>'
        if marker in content and b'__greenlifeCallTrackingInstalled' not in content:
            payload = (_CALL_CENTER_STAFF_STYLE + _CALL_TRACKING_SCRIPT).encode('utf-8')
            response.content = content.replace(marker, payload + marker, 1)
            if response.has_header('Content-Length'):
                response['Content-Length'] = str(len(response.content))
        return response
