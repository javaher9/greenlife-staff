from django.conf import settings
from django.db import models


ASSISTANT_CHOICES = (('yasaman', 'یاسمن'), ('camellia', 'کاملیا'), ('rose', 'رز'))
OPEN_ASSISTANT_JOB_STATES = ('queued', 'retry')


class AssistantCallQueue(models.Model):
    assistant = models.CharField(max_length=12, choices=ASSISTANT_CHOICES, unique=True)
    paused = models.BooleanField(default=False)
    updated_at = models.DateTimeField(auto_now=True)


class AssistantCallJob(models.Model):
    STATUS_CHOICES = (
        ('queued', 'در صف'),
        ('retry', 'در انتظار تلاش مجدد'),
        ('completed', 'انجام شد'),
        ('failed', 'ناموفق'),
        ('cancelled', 'لغو شد'),
    )

    queue = models.ForeignKey(
        AssistantCallQueue, to_field='assistant', on_delete=models.PROTECT, related_name='jobs',
    )
    lead = models.ForeignKey('core.ReferralLead', on_delete=models.CASCADE, related_name='assistant_call_jobs')
    consent_session = models.OneToOneField(
        'core.LeadCallSession', on_delete=models.CASCADE, related_name='assistant_call_job',
    )
    scheduled_for = models.DateTimeField()
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default='queued')
    attempts = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=('queue', 'status', 'scheduled_for'), name='asst_job_queue_due_idx')]
        constraints = [
            models.UniqueConstraint(
                fields=('lead',), condition=models.Q(status__in=OPEN_ASSISTANT_JOB_STATES),
                name='one_open_assistant_job_per_lead',
            ),
        ]
