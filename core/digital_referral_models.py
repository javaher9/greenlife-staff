import uuid

from django.contrib.auth.models import User
from django.db import models

from .models import EmployeeProfile


class DigitalReferralProfile(models.Model):
    SOURCE_CHOICES = [
        ('instagram', 'Instagram'),
        ('greenlife', 'GreenLifeClinics.com'),
        ('drjavaherian', 'DrJavaherian.com'),
        ('rejim', 'Rejim.ir'),
        ('other', 'سایر'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='digital_referral_profile')
    sponsor = models.ForeignKey('self', on_delete=models.PROTECT, null=True, blank=True, related_name='members')
    source = models.CharField(max_length=24, choices=SOURCE_CHOICES, db_index=True)
    source_detail = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=30, db_index=True)
    photo = models.ImageField(upload_to='digital-referrals/people/%Y/%m/', null=True, blank=True)
    referral_code = models.CharField(max_length=24, unique=True, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'core'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['source', '-created_at'], name='digref_source_created_idx')]

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    @property
    def display_photo(self):
        return self.photo

    @property
    def level(self):
        if not self.sponsor_id:
            return 1
        return 2

    @classmethod
    def new_code(cls):
        while True:
            code = f'GLD{uuid.uuid4().hex[:8].upper()}'
            if not cls.objects.filter(referral_code=code).exists():
                return code


class DigitalReferralLead(models.Model):
    STATUS_CHOICES = [
        ('new', 'جدید'),
        ('contacted', 'تماس گرفته شد'),
        ('appointment', 'نوبت ثبت شد'),
        ('visited', 'مراجعه کرد'),
        ('won', 'فروش موفق'),
        ('lost', 'ناموفق'),
    ]

    referrer = models.ForeignKey(DigitalReferralProfile, on_delete=models.PROTECT, related_name='digital_leads')
    full_name = models.CharField(max_length=140)
    phone = models.CharField(max_length=30, db_index=True)
    interested_service = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='new', db_index=True)
    assigned_to = models.ForeignKey(EmployeeProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_digital_referral_leads')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = 'core'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['referrer', 'status', '-created_at'], name='diglead_ref_status_idx')]

    def __str__(self):
        return f'{self.full_name} - {self.phone}'
