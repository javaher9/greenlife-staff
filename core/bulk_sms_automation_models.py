"""Persisted executive bulk schedules, immutable runs and opt-in participation."""
import uuid

from django.conf import settings
from django.db import models


class BulkSmsAutomation(models.Model):
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    name = models.CharField(max_length=100)
    status = models.CharField(max_length=12, default='draft', db_index=True)
    config = models.JSONField(default=dict)
    revision = models.PositiveIntegerField(default=1)
    next_run_at = models.DateTimeField(null=True, blank=True, db_index=True)
    consent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class BulkSmsAutomationRun(models.Model):
    automation = models.ForeignKey(BulkSmsAutomation, on_delete=models.PROTECT, related_name='runs')
    scheduled_for = models.DateTimeField()
    config = models.JSONField(default=dict)
    status = models.CharField(max_length=12, default='running', db_index=True)
    next_step = models.PositiveSmallIntegerField(default=0)
    next_step_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['automation', 'scheduled_for'], name='sms_auto_unique_run')]


class BulkSmsAutomationStep(models.Model):
    run = models.ForeignKey(BulkSmsAutomationRun, on_delete=models.PROTECT, related_name='steps')
    index = models.PositiveSmallIntegerField()
    campaign = models.OneToOneField('core.BulkSmsCampaign', on_delete=models.PROTECT, null=True, blank=True, related_name='automation_step')
    paused_by_automation = models.BooleanField(default=False)
    note = models.CharField(max_length=240, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['run', 'index'], name='sms_auto_unique_step')]


class BulkSmsParticipation(models.Model):
    run = models.ForeignKey(BulkSmsAutomationRun, on_delete=models.PROTECT, related_name='participants')
    number = models.CharField(max_length=11)
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    participated_at = models.DateTimeField(null=True, blank=True)
    points = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['run', 'number'], name='sms_auto_unique_participant')]
