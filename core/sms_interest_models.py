import uuid
from django.conf import settings
from django.db import models


class SmsInterestInvitation(models.Model):
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    number = models.CharField(max_length=11)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    choice = models.CharField(max_length=16, blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    callback_at = models.DateTimeField(null=True, blank=True)
    is_test = models.BooleanField(default=True)

