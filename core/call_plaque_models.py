"""Persisted call-plaque drafts and immutable call snapshots.

Only a finalized snapshot affects the client profile or operational call result.
Drafts are deliberately excluded from the call history and readiness scoring.
"""
import uuid

from django.conf import settings
from django.db import models


class LeadCallSession(models.Model):
    STATES = [('draft', 'پیش‌نویس'), ('final', 'تماس ثبت‌شده'), ('discard', 'بستن پیش‌نویس')]
    lead = models.ForeignKey('core.ReferralLead', on_delete=models.CASCADE, related_name='call_sessions')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='lead_call_sessions')
    request_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    state = models.CharField(max_length=10, choices=STATES)
    revision = models.PositiveIntegerField()
    data = models.JSONField(default=dict)
    readiness = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']
        indexes = [models.Index(fields=['lead', 'state', '-created_at'], name='lead_call_history_idx')]


class LeadCallProfile(models.Model):
    lead = models.OneToOneField('core.ReferralLead', on_delete=models.CASCADE, related_name='call_profile')
    revision = models.PositiveIntegerField(default=0)
    data = models.JSONField(default=dict)
    answer_evidence = models.JSONField(default=dict)
    readiness = models.JSONField(default=dict)
    do_not_contact = models.BooleanField(default=False, db_index=True)
    latest_session = models.ForeignKey(LeadCallSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    draft = models.ForeignKey(LeadCallSession, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)
