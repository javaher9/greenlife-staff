"""Personnel account access helpers shared by management actions."""
from django.contrib.sessions.models import Session
from django.utils import timezone


def revoke_staff_sessions(user_id):
    """Delete all live Django DB sessions owned by one account.

    Public HTTPS and LAN use distinct cookie names but share the Session table.
    Django also refuses disabled auth.User accounts on subsequent requests.
    """
    keys=[]
    for session in Session.objects.filter(expire_date__gt=timezone.now()).iterator(chunk_size=200):
        try:
            authenticated_id=session.get_decoded().get('_auth_user_id')
        except (ValueError,TypeError,KeyError):
            continue
        if str(authenticated_id)==str(user_id):
            keys.append(session.session_key)
    if keys:
        Session.objects.filter(session_key__in=keys).delete()
    return len(keys)
