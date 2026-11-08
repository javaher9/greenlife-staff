import uuid
import secrets
import string
from django.conf import settings
from django.db import models


def sms_interest_short_code():
    alphabet = string.ascii_letters + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(7))


class SmsInterestInvitation(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    short_code = models.CharField(max_length=7, unique=True, db_index=True, default=sms_interest_short_code, editable=False)
    number = models.CharField(max_length=11)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    choice = models.CharField(max_length=16, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    callback_at = models.DateTimeField(null=True, blank=True)
    is_test = models.BooleanField(default=True)
