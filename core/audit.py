SENSITIVE_KEYS={'password','password_confirm','new_password','csrfmiddlewaretoken','token','api_key','secret','authorization'}

def _safe_payload(request):
    data={}
    try:
        for key in request.POST.keys():
            if key.lower() in SENSITIVE_KEYS:
                data[key]='***'
            else:
                vals=request.POST.getlist(key)
                value=vals if len(vals)>1 else (vals[0] if vals else '')
                data[key]=str(value)[:300]
    except Exception:
        pass
    return data

def _ip(request):
    forwarded=request.META.get('HTTP_X_FORWARDED_FOR','')
    return (forwarded.split(',')[0].strip() if forwarded else request.META.get('REMOTE_ADDR')) or None

class AuditLogMiddleware:
    """Append-only audit trail for authenticated write requests."""
    def __init__(self,get_response): self.get_response=get_response
    def __call__(self,request):
        response=self.get_response(request)
        if request.method in {'POST','PUT','PATCH','DELETE'} and getattr(request,'user',None) and request.user.is_authenticated:
            try:
                from .models import AuditLog
                AuditLog.objects.create(
                    actor=request.user,
                    action='write',
                    path=request.path[:255],
                    method=request.method,
                    summary=f'{request.method} {request.path}'[:250],
                    metadata={'status_code':response.status_code,'payload':_safe_payload(request)},
                    ip_address=_ip(request),
                )
            except Exception:
                # Audit logging must never break the business action.
                pass
        return response
