from django.conf import settings
from django.db import models


class IntakeInvitation(models.Model):
    appointment = models.OneToOneField('core.VisitAppointment', on_delete=models.CASCADE, related_name='intake_invitation')
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    answers = models.JSONField(default=dict, blank=True)
    consent_version = models.CharField(max_length=20, blank=True)
    consent_at = models.DateTimeField(null=True, blank=True)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    sms_status = models.CharField(max_length=20, default='pending')
    class Meta:
        ordering = ['-id']
