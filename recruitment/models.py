from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

ORGANIZATIONS = [('clinic','کلینیک'),('camp','کمپ'),('office','دفتر مرکزی'),('other','سایر پروژه‌ها')]
JOB_STATUSES = [('draft','پیش‌نویس'),('open','در حال جذب'),('paused','متوقف'),('closed','تکمیل‌شده')]
STAGES = [('new','جدید'),('screening','بررسی اولیه'),('interview','مصاحبه'),('evaluation','ارزیابی عملی'),('decision','تصمیم‌گیری'),('offer','پیشنهاد همکاری'),('accepted','پذیرش پیشنهاد'),('started','شروع کار'),('probation','دوره آزمایشی'),('hired','تثبیت همکاری'),('rejected','ردشده'),('withdrawn','انصراف متقاضی'),('talent','بانک استعدادها'),('salary_declined','عدم توافق حقوق')]
TERMINAL_STAGES = {'hired','rejected','withdrawn','talent','salary_declined'}
SOURCES = [('manual','ثبت دستی'),('divar','دیوار'),('linkedin','لینکدین'),('website','سایت'),('instagram','اینستاگرام'),('referral','معرفی'),('other','سایر')]
AD_STATUSES = [('draft','پیش‌نویس'),('pending','در انتظار انتشار'),('review','در بررسی پلتفرم'),('active','فعال'),('expired','منقضی'),('rejected','ردشده توسط پلتفرم')]


class Job(models.Model):
    country = models.ForeignKey('core.Country', on_delete=models.PROTECT)
    branch = models.ForeignKey('core.Branch', on_delete=models.PROTECT, null=True, blank=True)
    organization = models.CharField(max_length=16, choices=ORGANIZATIONS, default='clinic')
    title = models.CharField(max_length=160)
    headcount = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1),MaxValueValidator(100)])
    description = models.TextField(blank=True, max_length=10000)
    requirements = models.TextField(blank=True, max_length=10000)
    expected_outcomes = models.TextField(blank=True, max_length=5000)
    location = models.CharField(max_length=240, blank=True)
    shift = models.CharField(max_length=240, blank=True)
    benefits = models.TextField(blank=True, max_length=3000)
    criteria = models.JSONField(default=list)
    salary_min = models.PositiveBigIntegerField(null=True, blank=True)
    salary_max = models.PositiveBigIntegerField(null=True, blank=True)
    budget_approved = models.BooleanField(default=False)
    budget_approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    requires_executive_approval = models.BooleanField(default=False)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='recruitment_jobs')
    status = models.CharField(max_length=12, choices=JOB_STATUSES, default='draft')
    target_date = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class Candidate(models.Model):
    country = models.ForeignKey('core.Country', on_delete=models.PROTECT)
    name = models.CharField(max_length=160)
    phone = models.CharField(max_length=20)
    email = models.EmailField(blank=True)
    city = models.CharField(max_length=120, blank=True)
    resume_text = models.TextField(blank=True, max_length=20000)
    resume_data = models.BinaryField(null=True, blank=True, editable=False)
    resume_name = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['country','phone'], name='recruitment_candidate_country_phone')]


class Application(models.Model):
    candidate = models.ForeignKey(Candidate, on_delete=models.PROTECT, related_name='applications')
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name='applications')
    stage = models.CharField(max_length=20, choices=STAGES, default='new')
    source = models.CharField(max_length=16, choices=SOURCES, default='manual')
    source_detail = models.CharField(max_length=300, blank=True)
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='recruitment_applications')
    next_action = models.CharField(max_length=300)
    next_action_at = models.DateTimeField(null=True, blank=True)
    interview_at = models.DateTimeField(null=True, blank=True)
    interview_location = models.CharField(max_length=300, blank=True)
    requested_salary = models.PositiveBigIntegerField(null=True, blank=True)
    offered_salary = models.PositiveBigIntegerField(null=True, blank=True)
    decision_reason = models.TextField(blank=True, max_length=5000)
    review_required = models.BooleanField(default=False)
    review_reason = models.CharField(max_length=500, blank=True)
    pending_stage = models.CharField(max_length=20, blank=True, choices=STAGES)
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_stage = models.CharField(max_length=20, blank=True, choices=STAGES)
    start_date = models.DateField(null=True, blank=True)
    probation_review_at = models.DateField(null=True, blank=True)
    probation_outcome = models.TextField(blank=True, max_length=5000)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']
        constraints = [models.UniqueConstraint(fields=['candidate','job'], name='recruitment_unique_application')]
        indexes = [models.Index(fields=['stage','next_action_at'])]


class Evaluation(models.Model):
    application = models.ForeignKey(Application, on_delete=models.CASCADE, related_name='evaluations')
    reviewer = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    scores = models.JSONField(default=list)
    total = models.DecimalField(max_digits=5, decimal_places=2)
    evidence = models.TextField(max_length=5000)
    recommendation = models.CharField(max_length=20, choices=[('advance','پیشنهاد ادامه'),('review','نیازمند بررسی'),('decline','پیشنهاد رد')])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['application','reviewer'], name='recruitment_unique_review')]


class Advertisement(models.Model):
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name='ads')
    source = models.CharField(max_length=16, choices=SOURCES, default='divar')
    title = models.CharField(max_length=160)
    body = models.TextField(max_length=15000)
    status = models.CharField(max_length=12, choices=AD_STATUSES, default='draft')
    url = models.URLField(max_length=1000, blank=True)
    cost = models.PositiveBigIntegerField(null=True, blank=True)
    external_id = models.CharField(max_length=200, blank=True)
    expires_at = models.DateField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']


class Activity(models.Model):
    job = models.ForeignKey(Job, on_delete=models.PROTECT, related_name='activities')
    application = models.ForeignKey(Application, on_delete=models.PROTECT, null=True, blank=True, related_name='activities')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    kind = models.CharField(max_length=32)
    text = models.TextField(max_length=6000)
    changes = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
