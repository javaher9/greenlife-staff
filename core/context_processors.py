from django.conf import settings


def executive_access(request):
    user=getattr(request,'user',None)
    allowed=bool(
        user and getattr(user,'is_authenticated',False)
        and (user.username or '').lower() in settings.EXECUTIVE_USERNAMES
    )
    return {'executive_access':allowed}
