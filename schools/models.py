import uuid
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


class Organization(models.Model):
    # Schools are the first organization type; future company programs stay separate.
    kind = models.CharField(max_length=20, default='school', choices=[('school', 'مدرسه')])
    name = models.CharField('نام مدرسه', max_length=160)
    branch = models.ForeignKey('core.Branch', on_delete=models.PROTECT)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['kind', 'name', 'branch'], name='schools_unique_org')]

    def __str__(self):
        return self.name


class SchoolProgram(models.Model):
    STATES = [('negotiating', 'در حال مذاکره'), ('prepared', 'آماده دعوت'), ('open', 'ثبت‌نام فعال'), ('paused', 'پذیرش متوقف'), ('finished', 'پایان دوره')]
    organization = models.ForeignKey(Organization, on_delete=models.PROTECT, related_name='programs')
    title = models.CharField('نام گروه / دوره', max_length=120, default='رشد فرزند، سلامت خانواده')
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    capacity = models.PositiveIntegerField('ظرفیت خانواده', default=50, validators=[MinValueValidator(1), MaxValueValidator(10000)])
    state = models.CharField('وضعیت', max_length=20, choices=STATES, default='prepared')
    starts_on = models.DateField('شروع ثبت‌نام', null=True, blank=True)
    ends_on = models.DateField('پایان ثبت‌نام', null=True, blank=True)
    terms = models.TextField('خدمات و هزینه‌ها', max_length=2000)
    coordinator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='school_programs')
    contact_name = models.CharField('رابط مدرسه', max_length=140, blank=True)
    contact_phone = models.CharField('شماره رابط', max_length=24, blank=True)
    invitation_views = models.PositiveIntegerField(default=0)
    recorded_cost = models.DecimalField('هزینه ثبت‌شده طرح (تومان)', max_digits=15, decimal_places=0, null=True, blank=True, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def is_open(self):
        from django.utils import timezone
        today = timezone.localdate()
        return self.state == 'open' and (not self.starts_on or self.starts_on <= today) and (not self.ends_on or self.ends_on >= today) and self.organization.branch.is_active


class FamilyEnrollment(models.Model):
    STATES = [('pending', 'منتظر فعال‌سازی اپ'), ('waiting', 'فهرست انتظار'), ('ready', 'آماده نوبت‌دهی'), ('booked', 'نوبت قطعی'), ('attended', 'مراجعه کرده'), ('cancelled', 'لغو شده')]
    OCCUPIED = ('ready', 'booked', 'attended')
    OUTCOMES = [('none', 'بدون درخواست'), ('requested', 'درخواست مشاوره'), ('consulted', 'مشاوره انجام شد'), ('treatment', 'شروع درمان'), ('declined', 'عدم تمایل')]
    program = models.ForeignKey(SchoolProgram, on_delete=models.PROTECT, related_name='enrollments')
    member = models.ForeignKey('core.CustomerPortalMember', on_delete=models.PROTECT, related_name='school_enrollments')
    parent_name = models.CharField(max_length=140)
    consent_at = models.DateTimeField()
    consent_version = models.CharField(max_length=30, default='schools-v1')
    terms_snapshot = models.TextField()
    adult_opt_in = models.BooleanField(default=False)
    adult_opt_in_at = models.DateTimeField(null=True, blank=True)
    adult_outcome = models.CharField(max_length=16, choices=OUTCOMES, default='none')
    status = models.CharField(max_length=16, choices=STATES, default='pending')
    app_activated_at = models.DateTimeField(null=True, blank=True)
    appointment_at = models.DateTimeField(null=True, blank=True)
    visit_appointment = models.OneToOneField('core.VisitAppointment', on_delete=models.SET_NULL, null=True, blank=True, related_name='school_family')
    staff_note = models.CharField(max_length=500, blank=True)
    next_follow_up_at = models.DateTimeField('پیگیری بعدی', null=True, blank=True)
    contract_amount = models.DecimalField('مبلغ قرارداد والد (تومان)', max_digits=15, decimal_places=0, null=True, blank=True, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['program', 'member'], name='schools_one_family_per_program')]
        ordering = ['-created_at']


class Child(models.Model):
    enrollment = models.ForeignKey(FamilyEnrollment, on_delete=models.PROTECT, related_name='children')
    name = models.CharField('نام فرزند', max_length=140)
    birth_date = models.DateField('تاریخ تولد (میلادی)')
    sex = models.CharField('جنس برای نمودار رشد', max_length=1, choices=[('f', 'دختر'), ('m', 'پسر')])


class GrowthRecord(models.Model):
    child = models.ForeignKey(Child, on_delete=models.PROTECT, related_name='growth_records')
    measured_on = models.DateField('تاریخ ارزیابی (میلادی)')
    height_cm = models.DecimalField('قد (سانتی‌متر)', max_digits=5, decimal_places=1, validators=[MinValueValidator(40), MaxValueValidator(230)])
    weight_kg = models.DecimalField('وزن (کیلوگرم)', max_digits=5, decimal_places=1, validators=[MinValueValidator(5), MaxValueValidator(300)])
    interpretation = models.TextField('تفسیر پزشک و توصیه‌ها', max_length=3000)
    follow_up_on = models.DateField('تاریخ پیگیری (میلادی)', null=True, blank=True)
    clinician = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def bmi(self):
        return round(self.weight_kg / (self.height_cm / 100) ** 2, 1)

    class Meta:
        ordering = ['measured_on', 'id']


class SchoolAudit(models.Model):
    program = models.ForeignKey(SchoolProgram, on_delete=models.PROTECT, related_name='audit_entries')
    enrollment = models.ForeignKey(FamilyEnrollment, on_delete=models.PROTECT, null=True, blank=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True)
    event = models.CharField(max_length=60, choices=[('program_created','ساخت گروه مدرسه'),('program_updated','ویرایش شرایط گروه'),('family_coordinated','ثبت پیگیری و نوبت'),('parent_registered','ثبت‌نام والد'),('parent_activate','فعال‌سازی اپ'),('parent_cancel','لغو ثبت‌نام والد'),('parent_adult_opt_in','تغییر درخواست مشاوره والد'),('child_added','افزودن فرزند'),('clinical_record_created','ثبت گزارش پزشک')])
    details = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
