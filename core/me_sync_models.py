"""Account-owned app state; no client identity or client-issued rewards."""
from django.db import models


class MeAccountState(models.Model):
    member = models.OneToOneField('core.CustomerPortalMember', on_delete=models.CASCADE, related_name='me_state')
    version = models.PositiveIntegerField(default=0)
    values = models.JSONField(default=dict)
    consent_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)


class MeDailyAward(models.Model):
    member = models.ForeignKey('core.CustomerPortalMember', on_delete=models.CASCADE, related_name='me_awards')
    day = models.DateField()
    granted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['member', 'day'], name='me_award_member_day_unique')]


class MeSyncAudit(models.Model):
    member = models.ForeignKey('core.CustomerPortalMember', on_delete=models.CASCADE)
    version = models.PositiveIntegerField()
    action = models.CharField(max_length=24)
    created_at = models.DateTimeField(auto_now_add=True)
