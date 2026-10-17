from django.db import models


class CallCenterRoutingDay(models.Model):
    """Durable daily queue snapshot and receipts; also serializes all routers."""

    date = models.DateField(unique=True)
    opening_at = models.DateTimeField()
    opening_lead_ids = models.JSONField(default=list)
    early_operator_ids = models.JSONField(default=list)
    allocation_counts = models.JSONField(default=dict)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-date']
