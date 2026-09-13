from django.conf import settings

from .call_center_identity import FlowerUserProxy


def executive_access(request):
    user=getattr(request,'user',None)
    allowed=bool(
        user and getattr(user,'is_authenticated',False)
        and (user.username or '').lower() in settings.EXECUTIVE_USERNAMES
    )
    return {'executive_access':allowed}


def call_center_flower_user(request):
    """Use the operator's flower nickname only inside call-center UI pages."""
    user=getattr(request,'user',None)
    if not user or not getattr(user,'is_authenticated',False):
        return {}
    if not request.path.startswith('/call-center/'):
        return {}
    profile=getattr(user,'profile',None)
    if not profile or profile.role!='call_center':
        return {}
    return {'user':FlowerUserProxy(user)}
