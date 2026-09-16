from django.conf import settings
from .call_center_identity import FlowerUserProxy

def executive_access(request):
    user=getattr(request,'user',None)
    allowed=bool(user and getattr(user,'is_authenticated',False) and (user.username or '').lower() in settings.EXECUTIVE_USERNAMES)
    data={'executive_access':allowed}
    if allowed and request.path.startswith('/executive/'):
        try:
            from .executive_dashboard_context import build_executive_summary
            data['exec_summary']=build_executive_summary(user)
        except Exception:
            data['exec_summary']={}
    return data

def call_center_flower_user(request):
    user=getattr(request,'user',None)
    if not user or not getattr(user,'is_authenticated',False): return {}
    if not request.path.startswith('/call-center/'): return {}
    profile=getattr(user,'profile',None)
    if not profile or profile.role!='call_center': return {}
    return {'user':FlowerUserProxy(user)}
