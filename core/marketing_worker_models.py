"""Minimal, privacy-safe heartbeat for the read-only marketing monitor."""
from django.db import models


class MarketingWorkerState(models.Model):
    key = models.CharField(max_length=40, primary_key=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True, db_index=True)
    last_run_leads = models.PositiveIntegerField(default=0)
    activity = models.CharField(max_length=180, blank=True)
    last_error = models.CharField(max_length=240, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Marketing worker state"
        verbose_name_plural = "Marketing worker states"
