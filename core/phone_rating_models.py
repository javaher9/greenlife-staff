from django.db import models


class PhoneCallRating(models.Model):
    """A single customer score for an opaque PBX call reference."""

    call_id = models.UUIDField(unique=True, editable=False)
    operator = models.ForeignKey(
        'core.EmployeeProfile',
        null=True,
        on_delete=models.SET_NULL,
        related_name='phone_call_ratings',
    )
    score = models.PositiveSmallIntegerField()
    rated_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(score__gte=1, score__lte=5),
                name='phone_call_rating_score_1_5',
            ),
        ]
