"""Verified customer self-service: never authorize by patient ID or phone alone."""
from django.db import models
from django.contrib.auth.models import User


class CustomerPortalMember(models.Model):
    phone=models.CharField(max_length=11,unique=True)
    full_name=models.CharField(max_length=140,blank=True)
    referral_code=models.CharField(max_length=24,unique=True)
    created_at=models.DateTimeField(auto_now_add=True)
    last_login_at=models.DateTimeField(null=True,blank=True)

    def __str__(self): return self.phone


class CustomerPortalOTP(models.Model):
    phone=models.CharField(max_length=11,unique=True)
    code_hash=models.CharField(max_length=128,blank=True)
    expires_at=models.DateTimeField(null=True,blank=True)
    sent_at=models.DateTimeField(null=True,blank=True)
    window_started_at=models.DateTimeField(null=True,blank=True)
    sends_in_window=models.PositiveSmallIntegerField(default=0)
    failed_attempts=models.PositiveSmallIntegerField(default=0)


class CustomerServiceRequest(models.Model):
    KINDS=[('visit','درخواست ویزیت'),('device','درخواست نوبت دستگاه'),('network','درخواست عضویت شبکه فروش')]
    STATUSES=[
        ('pending','در انتظار بررسی'),('contacted','در حال پیگیری'),
        ('booked','نوبت تأیید شد'),('declined','بسته شد'),
    ]
    DAYPARTS=[('any','فرقی ندارد'),('morning','صبح'),('afternoon','بعدازظهر')]
    member=models.ForeignKey(CustomerPortalMember,on_delete=models.PROTECT,related_name='requests')
    kind=models.CharField(max_length=12,choices=KINDS)
    branch=models.ForeignKey('core.Branch',on_delete=models.PROTECT,related_name='customer_requests')
    preferred_date=models.DateField(null=True,blank=True)
    daypart=models.CharField(max_length=12,choices=DAYPARTS,default='any')
    note=models.CharField(max_length=300,blank=True)
    status=models.CharField(max_length=12,choices=STATUSES,default='pending',db_index=True)
    assigned_to=models.ForeignKey('core.EmployeeProfile',on_delete=models.SET_NULL,null=True,blank=True,related_name='customer_service_requests')
    visit_appointment=models.ForeignKey('core.VisitAppointment',on_delete=models.SET_NULL,null=True,blank=True)
    device_session=models.ForeignKey('core.DeviceSessionBooking',on_delete=models.SET_NULL,null=True,blank=True)
    staff_note=models.CharField(max_length=300,blank=True)
    resolved_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True,db_index=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        ordering=['-created_at','-id']
        constraints=[
            models.UniqueConstraint(
                fields=['member','kind'],
                condition=models.Q(status__in=('pending','contacted')),
                name='uniq_cust_open_kind'
            )
        ]


class CustomerClubReferral(models.Model):
    STATUS=[('pending','منتظر تأیید مراجعه'),('qualified','تأیید شده')]
    referrer=models.ForeignKey(CustomerPortalMember,on_delete=models.PROTECT,related_name='invited_members')
    invited=models.OneToOneField(CustomerPortalMember,on_delete=models.PROTECT,related_name='invitation')
    status=models.CharField(max_length=12,choices=STATUS,default='pending')
    qualified_at=models.DateTimeField(null=True,blank=True)
    qualified_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at']


class CustomerClubPoints(models.Model):
    member=models.ForeignKey(CustomerPortalMember,on_delete=models.PROTECT,related_name='points_entries')
    referral=models.OneToOneField(CustomerClubReferral,on_delete=models.PROTECT,related_name='points_entry')
    amount=models.PositiveIntegerField()
    approved_by=models.ForeignKey(User,on_delete=models.PROTECT)
    created_at=models.DateTimeField(auto_now_add=True)


class CustomerClubPolicy(models.Model):
    id=models.PositiveSmallIntegerField(primary_key=True,default=1,editable=False)
    enabled=models.BooleanField(default=False)
    referral_points=models.PositiveIntegerField(default=0)
    updated_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True)
    updated_at=models.DateTimeField(auto_now=True)
