from io import BytesIO
from uuid import uuid4

from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from PIL import Image, ImageOps

from .models import Attendance, EmployeeProfile


@receiver(post_save, sender=User)
def ensure_employee_profile(sender, instance, created, **kwargs):
    """Every application user must have the profile expected by the UI."""
    if created:
        EmployeeProfile.objects.get_or_create(
            user=instance,
            defaults={
                'role': 'admin' if instance.is_superuser else 'employee',
                'is_active': instance.is_active,
            },
        )


@receiver(pre_save, sender=EmployeeProfile)
def compress_employee_avatar(sender, instance, **kwargs):
    """Resize and compress newly uploaded personnel photos before storage.

    Profile photos do not need phone-camera resolution. New uploads are limited
    to 1200x1200 and saved as WebP. We progressively lower quality only when
    needed so the stored file normally stays well below 700 KB while remaining
    visually sharp for avatars/profile pages.
    """
    avatar = getattr(instance, 'avatar', None)
    if not avatar:
        return

    # Do not recompress the same stored photo whenever another profile field is
    # saved. Only process a newly selected/replaced image.
    if instance.pk:
        previous = sender.objects.filter(pk=instance.pk).values_list('avatar', flat=True).first()
        if previous and previous == avatar.name:
            return

    try:
        avatar.open('rb')
        image = Image.open(avatar)
        image = ImageOps.exif_transpose(image)
        image.load()

        # Profile UI never displays more than a small portrait; 1200 px leaves
        # ample headroom for retina/high-density screens without wasting space.
        image.thumbnail((1200, 1200), Image.Resampling.LANCZOS)

        if image.mode not in ('RGB', 'RGBA'):
            image = image.convert('RGB')

        output = BytesIO()
        target_bytes = 700 * 1024
        for quality in (82, 76, 70, 64):
            output.seek(0)
            output.truncate(0)
            image.save(output, format='WEBP', quality=quality, method=6)
            if output.tell() <= target_bytes:
                break

        output.seek(0)
        instance.avatar = ContentFile(
            output.read(),
            name=f'avatar-{uuid4().hex[:16]}.webp',
        )
    except Exception:
        # Form validation will surface invalid images. If Pillow cannot process
        # an otherwise accepted file, keep the original upload rather than
        # blocking the personnel record save.
        try:
            avatar.seek(0)
        except Exception:
            pass


@receiver(post_save, sender=Attendance)
def release_pending_call_center_leads(sender, instance, **kwargs):
    """Release the pending lead queue when a call-center operator checks in.

    The routing engine itself decides whether the overnight queue is ready to be
    released (Friday duty, the whole expected team present, or 11:00+). Running
    after commit ensures the new attendance row is visible to the routing query.
    """
    if not instance.check_in or instance.check_out:
        return
    try:
        profile = instance.user.profile
    except EmployeeProfile.DoesNotExist:
        return
    if (
        profile.role != 'call_center'
        or not profile.is_active
        or not instance.user.is_active
    ):
        return

    def _release():
        from .lead_routing import release_pending_leads_if_ready
        release_pending_leads_if_ready()

    transaction.on_commit(_release)
