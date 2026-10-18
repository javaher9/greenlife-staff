"""Persistent daily campaign proposal. No recipient phone or automatic dispatch."""
from django.db import models


class MarketingSmsPlan(models.Model):
    day = models.DateField(unique=True)
    segment_key = models.CharField(max_length=64)
    segment_title = models.CharField(max_length=100)
    body = models.TextField(max_length=600)
    rationale = models.CharField(max_length=250)
    candidate_count = models.PositiveIntegerField(null=True, blank=True)
    preview_limited = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default="proposal")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-day"]
        verbose_name = "Daily SMS strategy proposal"
