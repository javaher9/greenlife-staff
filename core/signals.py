from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import EmployeeProfile


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
