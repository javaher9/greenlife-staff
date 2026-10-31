"""Progress photos linked to patient scans; never expose file URLs directly."""
import uuid
from django.conf import settings
from django.db import models
from django.utils import timezone


def progress_photo_path(instance, filename):
    return f"body_progress_private/{timezone.now():%Y/%m}/{uuid.uuid4().hex}.jpg"


class BodyProgressPhoto(models.Model):
    PHASE_CHOICES = [('baseline', 'قبل از شروع'), ('followup', 'پیگیری')]
    ANGLE_CHOICES = [('front', 'روبه‌رو'), ('side', 'نیم‌رخ'), ('back', 'پشت')]

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    patient = models.ForeignKey('core.PatientProfile', on_delete=models.CASCADE, related_name='progress_photos')
    scan = models.ForeignKey('core.BodyAnalysisRecord', on_delete=models.SET_NULL, null=True, blank=True, related_name='progress_photos')
    image = models.ImageField(upload_to=progress_photo_path)
    phase = models.CharField(max_length=12, choices=PHASE_CHOICES)
    angle = models.CharField(max_length=8, choices=ANGLE_CHOICES)
    taken_at = models.DateTimeField(default=timezone.now, db_index=True)
    consent_recorded_at = models.DateTimeField()
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='patient_progress_photos')
    is_visible = models.BooleanField(default=True)

    class Meta:
        ordering = ['-taken_at', '-id']
        indexes = [models.Index(fields=['patient', 'taken_at'], name='body_photo_patient_day_idx')]

    def __str__(self):
        return f"{self.patient_id}/{self.phase}/{self.angle}"
