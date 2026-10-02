from django.db import models
from django.utils import timezone
from django.contrib.auth.models import User


class DeviceTypeSchedule(models.Model):
    code=models.CharField(max_length=24,unique=True)
    name=models.CharField(max_length=100)
    treatment_minutes=models.PositiveSmallIntegerField(default=60)
    preparation_minutes=models.PositiveSmallIntegerField(default=20)
    is_active=models.BooleanField(default=True)

    class Meta:
        ordering=['code']

    def __str__(self):
        return self.name


class BranchDeviceTypeStatus(models.Model):
    """Per-branch availability for a globally defined device type."""
    branch=models.ForeignKey('core.Branch',on_delete=models.CASCADE,related_name='device_type_statuses')
    device_type=models.ForeignKey(DeviceTypeSchedule,on_delete=models.CASCADE,related_name='branch_statuses')
    is_active=models.BooleanField(default=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=['branch','device_type'],name='uniq_branch_device_type_status')
        ]
        ordering=['branch_id','device_type_id']

    def __str__(self):
        state='active' if self.is_active else 'inactive'
        return f'{self.branch}: {self.device_type.code} ({state})'


class DeviceCabin(models.Model):
    branch=models.ForeignKey('core.Branch',on_delete=models.CASCADE,related_name='device_cabins')
    name=models.CharField(max_length=100)
    is_active=models.BooleanField(default=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=['branch','name'],name='uniq_branch_device_cabin_name')
        ]
        ordering=['name','id']

    def __str__(self):
        return f'{self.branch}: {self.name}'


class PhysicalDevice(models.Model):
    branch=models.ForeignKey('core.Branch',on_delete=models.CASCADE,related_name='physical_devices')
    device_type=models.ForeignKey(DeviceTypeSchedule,on_delete=models.PROTECT,related_name='physical_devices')
    name=models.CharField(max_length=100)
    cabin=models.ForeignKey(DeviceCabin,on_delete=models.SET_NULL,null=True,blank=True,related_name='assigned_devices')
    work_start=models.TimeField(default='08:30')
    last_start=models.TimeField(default='17:30')
    is_active=models.BooleanField(default=True)

    class Meta:
        constraints=[
            models.UniqueConstraint(fields=['branch','name'],name='uniq_branch_physical_device_name')
        ]
        ordering=['branch_id','name','id']

    def __str__(self):
        return f'{self.name} ({self.branch})'


class DeviceSessionBooking(models.Model):
    STATUS=[
        ('booked','رزرو شده'),
        ('arrived','حاضر شد'),
        ('late','دیر رسید'),
        ('completed','انجام شد'),
        ('no_show','نیامد'),
        ('cancelled','لغو شده'),
        ('rescheduled','جابجا شد'),
    ]
    branch=models.ForeignKey('core.Branch',on_delete=models.PROTECT,related_name='device_session_bookings')
    appointment=models.ForeignKey('core.VisitAppointment',on_delete=models.PROTECT,related_name='device_sessions')
    plan_item=models.ForeignKey('core.ConsultationPlanItem',on_delete=models.PROTECT,related_name='device_sessions')
    cabin=models.ForeignKey(DeviceCabin,on_delete=models.PROTECT,related_name='device_sessions')
    device=models.ForeignKey(PhysicalDevice,on_delete=models.PROTECT,related_name='primary_device_sessions')
    secondary_device=models.ForeignKey(PhysicalDevice,on_delete=models.PROTECT,null=True,blank=True,related_name='secondary_device_sessions')
    starts_at=models.DateTimeField(db_index=True)
    treatment_ends_at=models.DateTimeField()
    blocked_until=models.DateTimeField(db_index=True)
    treatment_minutes_snapshot=models.PositiveSmallIntegerField()
    preparation_minutes_snapshot=models.PositiveSmallIntegerField()
    status=models.CharField(max_length=12,choices=STATUS,default='booked',db_index=True)
    confirmation_sent_at=models.DateTimeField(null=True,blank=True)
    reminder_sent_at=models.DateTimeField(null=True,blank=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='created_device_sessions')
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)

    class Meta:
        ordering=['starts_at','id']
        indexes=[models.Index(fields=['branch','starts_at','blocked_until'],name='device_booking_branch_range')]

    def __str__(self):
        return f'{self.appointment.full_name} - {self.device.name} - {self.starts_at}'
