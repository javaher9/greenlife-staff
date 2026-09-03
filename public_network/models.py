import uuid

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db import models


def _new_code():
    return f'GLP{uuid.uuid4().hex[:9].upper()}'


class PublicNetworkMember(models.Model):
    SOURCE_CHOICES = [
        ('story', 'استوری گرین لایف'),
        ('referral', 'لینک معرف'),
        ('qr', 'QR معرف'),
        ('direct', 'ورود مستقیم'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='public_network_member')
    sponsor = models.ForeignKey(
        'self', on_delete=models.PROTECT, null=True, blank=True, related_name='members'
    )
    code = models.CharField(max_length=24, unique=True, db_index=True, default=_new_code)
    phone = models.CharField(max_length=30, db_index=True)
    photo = models.ImageField(upload_to='public-network/people/%Y/%m/')
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='direct', db_index=True)
    source_url = models.URLField(max_length=500, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['sponsor', 'is_active', '-created_at'], name='pubnet_sponsor_active_idx'),
            models.Index(fields=['source', '-created_at'], name='pubnet_source_date_idx'),
        ]

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    @property
    def display_name(self):
        return self.user.get_full_name() or self.user.username

    @property
    def depth(self):
        depth = 0
        node = self.sponsor
        seen = {self.pk} if self.pk else set()
        while node is not None and node.pk not in seen and depth < 100:
            seen.add(node.pk)
            depth += 1
            node = node.sponsor
        return depth

    def clean(self):
        super().clean()
        if self.pk and self.sponsor_id == self.pk:
            raise ValidationError({'sponsor': 'هر عضو نمی‌تواند معرف خودش باشد.'})
        node = self.sponsor
        seen = {self.pk} if self.pk else set()
        while node is not None:
            if node.pk in seen:
                raise ValidationError({'sponsor': 'ساختار شبکه نمی‌تواند حلقه داشته باشد.'})
            seen.add(node.pk)
            node = node.sponsor

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
