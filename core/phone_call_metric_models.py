from django.db import models


class PhoneCallMetric(models.Model):
    """One qualitative outcome and conversation duration for an external call."""

    call_id = models.UUIDField(unique=True, editable=False)
    direction = models.CharField(max_length=8, choices=[('inbound', 'ورودی'), ('outbound', 'خروجی')])
    outcome = models.CharField(max_length=10, choices=[('answered', 'پاسخ‌داده'), ('unanswered', 'بی‌پاسخ')])
    occurred_at = models.DateTimeField(db_index=True)
    duration_seconds = models.PositiveIntegerField()

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(direction__in=('inbound', 'outbound')),
                name='phone_metric_direction_valid',
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(outcome='answered') | models.Q(outcome='unanswered', duration_seconds=0)
                ),
                name='phone_metric_outcome_valid',
            ),
        ]
