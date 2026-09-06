import base64
import hashlib
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.utils import timezone

from .models import StaffCredential


def _fernet():
    material=getattr(settings,'CREDENTIAL_ENCRYPTION_KEY','') or settings.SECRET_KEY
    digest=hashlib.sha256(('greenlife-staff-credential-v1:'+material).encode('utf-8')).digest()
    return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value):
    if not value:
        return ''
    return _fernet().encrypt(value.encode('utf-8')).decode('ascii')


def decrypt_secret(value):
    if not value:
        return ''
    try:
        return _fernet().decrypt(value.encode('ascii')).decode('utf-8')
    except (InvalidToken, ValueError, TypeError):
        return ''


def credential_for(user):
    credential,_=StaffCredential.objects.get_or_create(user=user)
    return credential


def remember_desktop_password(user, plaintext, actor=None):
    credential=credential_for(user)
    credential.desktop_password_cipher=encrypt_secret(plaintext)
    credential.desktop_password_set_at=timezone.now()
    credential.updated_by=actor
    credential.save(update_fields=['desktop_password_cipher','desktop_password_set_at','updated_by','updated_at'])
    return credential


def change_desktop_password(user, plaintext, actor=None):
    user.set_password(plaintext)
    user.save(update_fields=['password'])
    return remember_desktop_password(user,plaintext,actor=actor)


def change_mobile_pin(user, pin, actor=None):
    credential=credential_for(user)
    credential.mobile_pin_hash=make_password(pin)
    credential.mobile_pin_cipher=encrypt_secret(pin)
    credential.mobile_pin_set_at=timezone.now()
    credential.mobile_failed_attempts=0
    credential.mobile_locked_until=None
    credential.updated_by=actor
    credential.save(update_fields=[
        'mobile_pin_hash','mobile_pin_cipher','mobile_pin_set_at',
        'mobile_failed_attempts','mobile_locked_until','updated_by','updated_at',
    ])
    return credential


def verify_mobile_pin(user, pin):
    credential=StaffCredential.objects.filter(user=user).first()
    if not credential or not credential.mobile_pin_hash:
        return None, 'not_set'

    now=timezone.now()
    if credential.mobile_locked_until and credential.mobile_locked_until>now:
        return False, 'locked'

    if check_password(pin,credential.mobile_pin_hash):
        credential.mobile_failed_attempts=0
        credential.mobile_locked_until=None
        credential.last_mobile_login=now
        credential.save(update_fields=['mobile_failed_attempts','mobile_locked_until','last_mobile_login','updated_at'])
        return True, 'ok'

    credential.mobile_failed_attempts=(credential.mobile_failed_attempts or 0)+1
    if credential.mobile_failed_attempts>=5:
        credential.mobile_locked_until=now+timedelta(minutes=10)
        credential.mobile_failed_attempts=0
        status='locked'
    else:
        status='invalid'
    credential.save(update_fields=['mobile_failed_attempts','mobile_locked_until','updated_at'])
    return False,status


def record_mobile_login(user):
    credential=credential_for(user)
    credential.last_mobile_login=timezone.now()
    credential.save(update_fields=['last_mobile_login','updated_at'])
    return credential


def record_desktop_login(user):
    credential=credential_for(user)
    credential.last_desktop_login=timezone.now()
    credential.save(update_fields=['last_desktop_login','updated_at'])
    return credential
