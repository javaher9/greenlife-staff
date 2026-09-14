from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_POST

from .models import ReferralLead


@login_required
@require_POST
def mark_call_started(request, pk):
    """Advance a brand-new call-center lead when the operator starts a call.

    Pressing the call button again never downgrades later outcomes such as
    appointment, visit, won or lost.
    """
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'call_center' or not profile.is_active:
        return JsonResponse({'ok': False, 'error': 'forbidden'}, status=403)

    lead = get_object_or_404(ReferralLead, pk=pk, assigned_to=profile)
    changed = False
    if lead.status == 'new':
        lead.status = 'contacted'
        lead.save(update_fields=['status', 'updated_at'])
        changed = True

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
    })


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

  function leadIdFor(link){
    var row=link.closest('.cc-v5-patient');
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

  function labelDashboardActions(){
    if(location.pathname.indexOf('/call-center/')!==0)return;
    var actions=document.querySelectorAll('a.cc-v5-action[href*="status=contacted"]');
    for(var i=0;i<actions.length;i++){
      var text=(actions[i].textContent||'').trim();
      if(text.indexOf('ثبت نتیجه تماس')!==-1){
        actions[i].textContent='✓ تماس گرفته شد';
      }
    }
  }

  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',labelDashboardActions);
  }else{
    labelDashboardActions();
  }

  document.addEventListener('click',function(event){
    var link=event.target.closest('a[href^="tel:"]');
    if(!link||location.pathname.indexOf('/call-center/')!==0)return;
    var leadId=leadIdFor(link);
    if(!leadId)return;

    var token=csrfToken();
    var body=new FormData();
    if(token)body.append('csrfmiddlewaretoken',token);
    var endpoint='/call-center/leads/'+leadId+'/call-started/';

    var row=link.closest('.cc-v5-patient');
    if(row){
      var badge=row.querySelector('.cc-v5-status');
      if(badge&&badge.textContent.trim()==='جدید')badge.textContent='تماس گرفته شد';
    }

    try{
      if(navigator.sendBeacon){
        navigator.sendBeacon(endpoint,body);
      }else{
        fetch(endpoint,{method:'POST',body:body,credentials:'same-origin',keepalive:true,
          headers:{'X-Requested-With':'XMLHttpRequest'}}).catch(function(){});
      }
    }catch(e){}
  },true);
})();
</script>'''


class CallCenterCallTrackingMiddleware:
    """Inject lightweight call tracking only into authenticated call-center HTML pages."""

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
            script = _CALL_TRACKING_SCRIPT.encode('utf-8')
            response.content = content.replace(marker, script + marker, 1)
            if response.has_header('Content-Length'):
                response['Content-Length'] = str(len(response.content))
        return response
