from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class Branch(models.Model):
    name = models.CharField(max_length=80, unique=True)
    is_active = models.BooleanField(default=True)
    work_start = models.TimeField(default='09:00')
    work_end = models.TimeField(default='17:00')
    grace_minutes = models.PositiveSmallIntegerField(default=15)
    # Attendance geofence. Configure these per branch in Django Admin.
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    attendance_radius_m = models.PositiveIntegerField(default=150)
    geofence_enabled = models.BooleanField(default=False)
    def __str__(self): return self.name

class ShiftGroup(models.Model):
    name=models.CharField(max_length=100)
    branch=models.ForeignKey(Branch,on_delete=models.CASCADE,related_name='shift_groups')
    default_shift=models.ForeignKey('WorkShift',on_delete=models.SET_NULL,null=True,blank=True,related_name='default_for_groups')
    is_active=models.BooleanField(default=True)
    note=models.CharField(max_length=250,blank=True)
    def __str__(self):
        return f'{self.branch} - {self.name}'

class EmployeeProfile(models.Model):
    ROLE_CHOICES=[('admin','مدیر سیستم'),('manager','مدیر شعبه'),('employee','کارمند')]
    user=models.OneToOneField(User,on_delete=models.CASCADE,related_name='profile')
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True)
    role=models.CharField(max_length=20,choices=ROLE_CHOICES,default='employee')
    shift_group=models.ForeignKey(ShiftGroup,on_delete=models.SET_NULL,null=True,blank=True,related_name='employees')
    job_title=models.CharField(max_length=120,blank=True)
    employee_code=models.CharField(max_length=30,blank=True,unique=True,null=True)
    phone=models.CharField(max_length=30,blank=True)
    start_date=models.DateField(null=True,blank=True)
    birth_date=models.DateField(null=True,blank=True)
    avatar=models.ImageField(upload_to='avatars/',null=True,blank=True)
    is_active=models.BooleanField(default=True)
    def __str__(self): return self.user.get_full_name() or self.user.username

class Task(models.Model):
    STATUS=[('todo','انجام نشده'),('doing','در حال انجام'),('done','انجام شده')]
    PRIORITY=[('low','کم'),('normal','متوسط'),('high','زیاد')]
    title=models.CharField(max_length=200)
    description=models.TextField(blank=True)
    assigned_to=models.ForeignKey(User,on_delete=models.CASCADE,related_name='tasks')
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,related_name='created_tasks')
    due_date=models.DateField(null=True,blank=True)
    status=models.CharField(max_length=10,choices=STATUS,default='todo')
    priority=models.CharField(max_length=10,choices=PRIORITY,default='normal')
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    def __str__(self): return self.title

class Announcement(models.Model):
    title=models.CharField(max_length=200)
    body=models.TextField()
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True)
    is_active=models.BooleanField(default=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.title

class SOPDocument(models.Model):
    title=models.CharField(max_length=200)
    description=models.TextField(blank=True)
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True)
    job_title=models.CharField(max_length=120,blank=True)
    file=models.FileField(upload_to='sop/',null=True,blank=True)
    content=models.TextField(blank=True)
    is_active=models.BooleanField(default=True)
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.title

class LeaveRequest(models.Model):
    TYPE=[('annual','مرخصی استحقاقی'),('sick','مرخصی استعلاجی'),('hourly','مرخصی ساعتی'),('mission','ماموریت')]
    STATUS=[('pending','در انتظار بررسی'),('approved','تایید شده'),('rejected','رد شده')]
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='leave_requests')
    request_type=models.CharField(max_length=20,choices=TYPE,default='annual')
    start_date=models.DateField()
    end_date=models.DateField()
    reason=models.TextField(blank=True)
    status=models.CharField(max_length=20,choices=STATUS,default='pending')
    manager_note=models.TextField(blank=True)
    reviewed_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='reviewed_leave_requests')
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return f'{self.user} - {self.get_request_type_display()}'


class JobDutyTemplate(models.Model):
    title=models.CharField(max_length=140)
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True,related_name='job_duties')
    job_title=models.CharField(max_length=120,blank=True,help_text='اگر خالی باشد برای همه سمت‌ها قابل استفاده است.')
    description=models.TextField()
    is_active=models.BooleanField(default=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='created_job_duties')
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.title

class Guideline(models.Model):
    AUDIENCE=[('all','همه پرسنل'),('branch','یک شعبه'),('job','یک سمت شغلی')]
    title=models.CharField(max_length=160)
    body=models.TextField()
    audience=models.CharField(max_length=20,choices=AUDIENCE,default='all')
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True,related_name='guidelines')
    job_title=models.CharField(max_length=120,blank=True)
    is_required=models.BooleanField(default=True)
    is_active=models.BooleanField(default=True)
    published_at=models.DateTimeField(auto_now_add=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='created_guidelines')
    def __str__(self): return self.title

class GuidelineAcknowledgement(models.Model):
    guideline=models.ForeignKey(Guideline,on_delete=models.CASCADE,related_name='acknowledgements')
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='guideline_acknowledgements')
    acknowledged_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['guideline','user'],name='uniq_guideline_ack')]
    def __str__(self): return f'{self.user} - {self.guideline}'


class DeviceIssue(models.Model):
    STATUS=[('new','جدید'),('reviewing','در حال بررسی'),('resolved','رفع شده')]
    reporter=models.ForeignKey(User,on_delete=models.CASCADE,related_name='reported_device_issues')
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True,related_name='device_issues')
    device_name=models.CharField(max_length=160)
    description=models.TextField()
    status=models.CharField(max_length=20,choices=STATUS,default='new')
    manager_note=models.TextField(blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    resolved_at=models.DateTimeField(null=True,blank=True)
    resolved_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='resolved_device_issues')
    class Meta:
        ordering=['-created_at']
    def __str__(self):
        return f'{self.device_name} - {self.reporter}'

class DailyReport(models.Model):
    PROCESS=[('pending','در انتظار پردازش'),('processed','پردازش شده'),('failed','خطا')]
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='reports')
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True)
    text=models.TextField(blank=True)
    audio=models.FileField(upload_to='reports/%Y/%m/%d/',blank=True,null=True)
    transcript=models.TextField(blank=True)
    ai_summary=models.TextField(blank=True)
    ai_tags=models.JSONField(default=list,blank=True)
    follow_up=models.TextField(blank=True)
    manager_comment=models.CharField(max_length=300,blank=True)
    manager_comment_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='report_comments')
    manager_comment_at=models.DateTimeField(null=True,blank=True)
    process_status=models.CharField(max_length=15,choices=PROCESS,default='pending')
    # Client-generated idempotency key: prevents duplicate report/voice rows
    # when the same POST is retried or submitted twice.
    client_submission_id=models.CharField(max_length=64,unique=True,null=True,blank=True,db_index=True)
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return f'{self.user} - {self.created_at:%Y-%m-%d}'

class Attendance(models.Model):
    STATUS=[('present','حاضر'),('late','تاخیر'),('absent','غایب'),('leave','مرخصی')]
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='attendance_records')
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True)
    date=models.DateField(default=timezone.localdate)
    check_in=models.DateTimeField(null=True,blank=True)
    check_out=models.DateTimeField(null=True,blank=True)
    status=models.CharField(max_length=12,choices=STATUS,default='present')
    note=models.CharField(max_length=250,blank=True)
    check_in_latitude=models.DecimalField(max_digits=9,decimal_places=6,null=True,blank=True)
    check_in_longitude=models.DecimalField(max_digits=9,decimal_places=6,null=True,blank=True)
    check_in_accuracy_m=models.FloatField(null=True,blank=True)
    check_in_distance_m=models.PositiveIntegerField(null=True,blank=True)
    check_in_location_status=models.CharField(max_length=20,default='legacy',choices=[
        ('verified','تأیید موقعیت'),('outside','خارج محدوده'),('low_accuracy','دقت پایین'),
        ('unavailable','موقعیت ناموجود'),('manual','ثبت دستی مدیر'),('legacy','قدیمی')
    ])
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['user','date'],name='uniq_attendance_user_date')]
        ordering=['-date','user__last_name']
    def __str__(self): return f'{self.user} - {self.date}'
    @property
    def worked_minutes(self):
        if not self.check_in or not self.check_out: return None
        return max(0,int((self.check_out-self.check_in).total_seconds()//60))


class ScoreEvent(models.Model):
    REASON=[('attendance','حضور به‌موقع'),('task','انجام وظیفه'),('report','گزارش روزانه'),('kpi','امتیاز KPI'),('bonus','امتیاز تشویقی'),('penalty','کسر امتیاز')]
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='score_events')
    points=models.IntegerField(default=0)
    reason=models.CharField(max_length=20,choices=REASON,default='bonus')
    description=models.CharField(max_length=250,blank=True)
    event_date=models.DateField(default=timezone.localdate)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='created_score_events')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-event_date','-created_at']
    def __str__(self): return f'{self.user} {self.points:+d}'

class KPIRecord(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='kpi_records')
    title=models.CharField(max_length=120)
    value=models.DecimalField(max_digits=10,decimal_places=2)
    target=models.DecimalField(max_digits=10,decimal_places=2,null=True,blank=True)
    score=models.PositiveSmallIntegerField(default=0,help_text='امتیاز از ۰ تا ۱۰۰')
    period_start=models.DateField()
    period_end=models.DateField()
    note=models.TextField(blank=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='created_kpi_records')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-period_end','-created_at']
    def __str__(self): return f'{self.user} - {self.title}'

class FinancialTransaction(models.Model):
    SOURCE=[('crm','CRM'),('sheet','Google Sheet'),('manual','دستی')]
    external_id=models.CharField(max_length=120,blank=True,null=True)
    source=models.CharField(max_length=20,choices=SOURCE,default='crm')
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True,related_name='financial_transactions')
    occurred_at=models.DateTimeField()
    amount=models.DecimalField(max_digits=18,decimal_places=2)
    payment_method=models.CharField(max_length=80,blank=True)
    service=models.CharField(max_length=160,blank=True)
    patient_ref=models.CharField(max_length=120,blank=True)
    raw_data=models.JSONField(default=dict,blank=True)
    synced_at=models.DateTimeField(auto_now=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-occurred_at']
        constraints=[models.UniqueConstraint(fields=['source','external_id'],name='uniq_finance_source_external',condition=models.Q(external_id__isnull=False))]
    def __str__(self): return f'{self.branch or "—"} - {self.amount}'

class IntegrationSyncLog(models.Model):
    STATUS=[('ok','موفق'),('error','خطا')]
    provider=models.CharField(max_length=30,default='crm')
    status=models.CharField(max_length=10,choices=STATUS)
    imported=models.PositiveIntegerField(default=0)
    updated=models.PositiveIntegerField(default=0)
    message=models.TextField(blank=True)
    started_at=models.DateTimeField()
    finished_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-finished_at']

class WorkShift(models.Model):
    name=models.CharField(max_length=100)
    branch=models.ForeignKey(Branch,on_delete=models.CASCADE,related_name='work_shifts')
    start_time=models.TimeField()
    end_time=models.TimeField()
    grace_minutes=models.PositiveSmallIntegerField(default=15)
    report_required=models.BooleanField(default=True)
    is_active=models.BooleanField(default=True)
    def __str__(self): return f'{self.branch} - {self.name}'

class ShiftAssignment(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='shift_assignments')
    shift=models.ForeignKey(WorkShift,on_delete=models.CASCADE,related_name='assignments')
    date=models.DateField()
    note=models.CharField(max_length=250,blank=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='created_shift_assignments')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['user','date'],name='uniq_shift_user_date')]
        ordering=['-date','user__last_name']
    def __str__(self): return f'{self.user} - {self.date} - {self.shift}'

class AttendanceCorrectionRequest(models.Model):
    STATUS=[('pending','در انتظار بررسی'),('approved','تایید شده'),('rejected','رد شده')]
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='attendance_corrections')
    attendance=models.ForeignKey(Attendance,on_delete=models.SET_NULL,null=True,blank=True,related_name='correction_requests')
    date=models.DateField()
    requested_check_in=models.DateTimeField(null=True,blank=True)
    requested_check_out=models.DateTimeField(null=True,blank=True)
    reason=models.TextField()
    status=models.CharField(max_length=20,choices=STATUS,default='pending')
    manager_note=models.TextField(blank=True)
    reviewed_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='reviewed_attendance_corrections')
    created_at=models.DateTimeField(auto_now_add=True)
    reviewed_at=models.DateTimeField(null=True,blank=True)
    class Meta: ordering=['-created_at']
    def __str__(self): return f'{self.user} - {self.date} - {self.get_status_display()}'

class StaffNotification(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='staff_notifications')
    title=models.CharField(max_length=160)
    message=models.TextField()
    notification_type=models.CharField(max_length=40,default='info')
    related_date=models.DateField(null=True,blank=True)
    is_read=models.BooleanField(default=False)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-created_at']
    def __str__(self): return f'{self.user} - {self.title}'


class EmployeeDocument(models.Model):
    TYPE=[
        ('contract','قرارداد'),
        ('identity','مدرک هویتی'),
        ('certificate','مدرک/گواهی'),
        ('training','آموزش'),
        ('other','سایر'),
    ]
    employee=models.ForeignKey(EmployeeProfile,on_delete=models.CASCADE,related_name='documents')
    document_type=models.CharField(max_length=20,choices=TYPE,default='other')
    title=models.CharField(max_length=160)
    file=models.FileField(upload_to='personnel/%Y/%m/')
    issue_date=models.DateField(null=True,blank=True)
    expiry_date=models.DateField(null=True,blank=True)
    note=models.TextField(blank=True)
    uploaded_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='uploaded_employee_documents')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at']
    def __str__(self): return f'{self.employee} - {self.title}'


class ChecklistTemplate(models.Model):
    name=models.CharField(max_length=140)
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True,related_name='checklist_templates')
    role=models.CharField(max_length=20,choices=EmployeeProfile.ROLE_CHOICES,blank=True)
    job_title=models.CharField(max_length=120,blank=True,help_text='اگر خالی باشد برای همه سمت‌های این نقش اعمال می‌شود.')
    is_active=models.BooleanField(default=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='created_checklist_templates')
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return self.name


class ChecklistItem(models.Model):
    template=models.ForeignKey(ChecklistTemplate,on_delete=models.CASCADE,related_name='items')
    title=models.CharField(max_length=180)
    description=models.TextField(blank=True)
    sort_order=models.PositiveSmallIntegerField(default=0)
    is_required=models.BooleanField(default=True)
    class Meta:
        ordering=['sort_order','id']
    def __str__(self): return self.title


class ChecklistCompletion(models.Model):
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='checklist_completions')
    item=models.ForeignKey(ChecklistItem,on_delete=models.CASCADE,related_name='completions')
    date=models.DateField(default=timezone.localdate)
    is_done=models.BooleanField(default=False)
    note=models.CharField(max_length=250,blank=True)
    completed_at=models.DateTimeField(null=True,blank=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['user','item','date'],name='uniq_checklist_user_item_date')]
        ordering=['-date','item__sort_order']
    def __str__(self): return f'{self.user} - {self.item} - {self.date}'


class PersonnelAction(models.Model):
    TYPES=[('praise','تشویق'),('notice','تذکر'),('warning','اخطار'),('note','یادداشت مدیریتی')]
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='personnel_actions')
    action_type=models.CharField(max_length=20,choices=TYPES)
    title=models.CharField(max_length=160)
    description=models.TextField()
    event_date=models.DateField(default=timezone.localdate)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,related_name='issued_personnel_actions')
    acknowledged_at=models.DateTimeField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-event_date','-created_at']

class PerformanceGoal(models.Model):
    SCOPE=[('employee','فردی'),('branch','شعبه')]
    METRICS=[('revenue','درآمد'),('tasks','Task تکمیل‌شده'),('reports','گزارش روزانه'),('attendance','حضور به‌موقع'),('custom','سفارشی')]
    title=models.CharField(max_length=160)
    scope=models.CharField(max_length=20,choices=SCOPE)
    metric=models.CharField(max_length=20,choices=METRICS,default='custom')
    employee=models.ForeignKey(User,on_delete=models.CASCADE,null=True,blank=True,related_name='performance_goals')
    branch=models.ForeignKey(Branch,on_delete=models.CASCADE,null=True,blank=True,related_name='performance_goals')
    target=models.DecimalField(max_digits=16,decimal_places=2)
    current_value=models.DecimalField(max_digits=16,decimal_places=2,default=0)
    start_date=models.DateField()
    end_date=models.DateField()
    is_active=models.BooleanField(default=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,related_name='created_goals')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-start_date']

class InternalRequest(models.Model):
    CATEGORIES=[('purchase','خرید'),('repair','تعمیر'),('it','IT'),('hr','منابع انسانی'),('finance','مالی'),('other','سایر')]
    STATUS=[('open','باز'),('doing','در حال انجام'),('done','انجام شد'),('rejected','رد شد')]
    PRIORITY=[('normal','عادی'),('high','مهم'),('urgent','فوری')]
    requester=models.ForeignKey(User,on_delete=models.CASCADE,related_name='internal_requests')
    category=models.CharField(max_length=20,choices=CATEGORIES)
    title=models.CharField(max_length=180)
    description=models.TextField()
    priority=models.CharField(max_length=20,choices=PRIORITY,default='normal')
    status=models.CharField(max_length=20,choices=STATUS,default='open')
    assigned_to=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='assigned_internal_requests')
    due_date=models.DateField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta: ordering=['-created_at']


class AuditLog(models.Model):
    actor=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='audit_logs')
    action=models.CharField(max_length=40)
    path=models.CharField(max_length=255)
    method=models.CharField(max_length=10)
    object_type=models.CharField(max_length=80,blank=True)
    object_id=models.CharField(max_length=80,blank=True)
    summary=models.CharField(max_length=250,blank=True)
    metadata=models.JSONField(default=dict,blank=True)
    ip_address=models.GenericIPAddressField(null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-created_at']
        indexes=[models.Index(fields=['-created_at'],name='core_auditl_created_idx'),models.Index(fields=['actor','-created_at'],name='core_auditl_actor_idx')]
    def __str__(self): return f'{self.actor or "system"} {self.action} {self.path}'

class ManagementEvent(models.Model):
    EVENT_TYPES=[('meeting','جلسه'),('deadline','سررسید'),('training','آموزش'),('reminder','یادآوری'),('other','سایر')]
    title=models.CharField(max_length=180)
    event_type=models.CharField(max_length=20,choices=EVENT_TYPES,default='other')
    date=models.DateField()
    time=models.TimeField(null=True,blank=True)
    branch=models.ForeignKey(Branch,on_delete=models.SET_NULL,null=True,blank=True,related_name='management_events')
    description=models.TextField(blank=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='created_management_events')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['date','time','title']


class CEOScoreSnapshot(models.Model):
    date=models.DateField()
    branch=models.ForeignKey(Branch,on_delete=models.CASCADE,null=True,blank=True,related_name='ceo_score_snapshots')
    score=models.PositiveSmallIntegerField()
    people=models.PositiveSmallIntegerField()
    operations=models.PositiveSmallIntegerField()
    revenue=models.PositiveSmallIntegerField()
    discipline=models.PositiveSmallIntegerField()
    details=models.JSONField(default=dict,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['-date']
        constraints=[models.UniqueConstraint(fields=['date','branch'],name='uniq_ceo_score_date_branch')]
    def __str__(self): return f'{self.date} - {self.branch or "all"} - {self.score}'


# =========================
# CAMP MODULE (v17)
# =========================
class CampSite(models.Model):
    name=models.CharField(max_length=120,default='کمپ گرین‌لایف')
    location=models.CharField(max_length=180,blank=True)
    owner_approval_threshold=models.DecimalField(max_digits=16,decimal_places=0,default=5000000,help_text='تومان')
    daily_photo_deadline=models.TimeField(default='18:00')
    is_active=models.BooleanField(default=True)
    def __str__(self): return self.name


class CampMembership(models.Model):
    ROLES=[('owner','Owner / Admin'),('supervisor','Camp Manager / Supervisor'),('worker','Worker / Staff'),('finance','Accountant / Finance')]
    site=models.ForeignKey(CampSite,on_delete=models.CASCADE,related_name='memberships')
    user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='camp_memberships')
    role=models.CharField(max_length=20,choices=ROLES,default='worker')
    is_active=models.BooleanField(default=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['site','user'],name='uniq_camp_membership')]
    def __str__(self): return f'{self.user} - {self.get_role_display()}'


class CampPurchaseRequest(models.Model):
    CATEGORIES=[('food','غذا'),('material','مصالح'),('tool','ابزار'),('fuel','سوخت'),('cleaning','نظافت'),('other','متفرقه')]
    UNITS=[('kg','کیلو'),('item','عدد'),('pack','بسته'),('liter','لیتر'),('meter','متر'),('bag','کیسه')]
    URGENCY=[('normal','عادی'),('important','مهم'),('urgent','فوری')]
    STATUS=[('pending','در انتظار تأیید'),('approved','تأیید شده'),('rejected','رد شده'),('purchased','خریداری شده'),('paid','پرداخت شده')]
    site=models.ForeignKey(CampSite,on_delete=models.CASCADE,related_name='purchase_requests')
    item_name=models.CharField(max_length=160)
    category=models.CharField(max_length=20,choices=CATEGORIES)
    quantity=models.DecimalField(max_digits=12,decimal_places=2)
    unit=models.CharField(max_length=20,choices=UNITS)
    estimated_amount=models.DecimalField(max_digits=16,decimal_places=0,default=0)
    reason=models.TextField(blank=True)
    requester=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='camp_purchase_requests')
    request_date=models.DateField(default=timezone.localdate)
    urgency=models.CharField(max_length=20,choices=URGENCY,default='normal')
    status=models.CharField(max_length=20,choices=STATUS,default='pending')
    attachment=models.FileField(upload_to='camp/purchases/%Y/%m/',null=True,blank=True)
    owner_approved_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='camp_owner_approvals')
    owner_approved_at=models.DateTimeField(null=True,blank=True)
    approved_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='camp_purchase_approvals')
    approved_at=models.DateTimeField(null=True,blank=True)
    rejection_note=models.CharField(max_length=250,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta: ordering=['-request_date','-created_at']
    def __str__(self): return self.item_name
    @property
    def requires_owner_approval(self):
        threshold=self.site.owner_approval_threshold if self.site_id else 5000000
        return self.estimated_amount >= threshold


class CampInvoice(models.Model):
    PAYMENT=[('cash','نقدی'),('card','کارت'),('account','حساب'),('debt','بدهی')]
    purchase=models.OneToOneField(CampPurchaseRequest,on_delete=models.CASCADE,related_name='invoice')
    final_amount=models.DecimalField(max_digits=16,decimal_places=0)
    vendor=models.CharField(max_length=160,blank=True)
    payment_method=models.CharField(max_length=20,choices=PAYMENT,default='card')
    invoice_image=models.ImageField(upload_to='camp/invoices/%Y/%m/',null=True,blank=True)
    description=models.TextField(blank=True)
    is_paid=models.BooleanField(default=False)
    paid_at=models.DateTimeField(null=True,blank=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='camp_invoices_created')
    created_at=models.DateTimeField(auto_now_add=True)
    def __str__(self): return f'{self.purchase} - {self.final_amount}'


class CampInventoryItem(models.Model):
    CATEGORIES=CampPurchaseRequest.CATEGORIES
    UNITS=CampPurchaseRequest.UNITS
    site=models.ForeignKey(CampSite,on_delete=models.CASCADE,related_name='inventory_items')
    name=models.CharField(max_length=140)
    category=models.CharField(max_length=20,choices=CATEGORIES)
    current_stock=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    unit=models.CharField(max_length=20,choices=UNITS)
    minimum_stock=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    last_purchase_date=models.DateField(null=True,blank=True)
    weekly_average_consumption=models.DecimalField(max_digits=12,decimal_places=2,default=0)
    is_active=models.BooleanField(default=True)
    class Meta:
        ordering=['category','name']
        constraints=[models.UniqueConstraint(fields=['site','name'],name='uniq_camp_inventory_item')]
    def __str__(self): return self.name
    @property
    def stock_status(self):
        if self.current_stock <= 0 or (self.minimum_stock and self.current_stock <= self.minimum_stock*.5): return 'critical'
        if self.current_stock <= self.minimum_stock: return 'low'
        return 'ok'


class CampInventoryMovement(models.Model):
    TYPES=[('in','ورود'),('out','خروج')]
    item=models.ForeignKey(CampInventoryItem,on_delete=models.CASCADE,related_name='movements')
    movement_type=models.CharField(max_length=10,choices=TYPES)
    quantity=models.DecimalField(max_digits=12,decimal_places=2)
    date=models.DateField(default=timezone.localdate)
    reason=models.CharField(max_length=200)
    reference_purchase=models.ForeignKey(CampPurchaseRequest,on_delete=models.SET_NULL,null=True,blank=True,related_name='inventory_movements')
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='camp_inventory_movements')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-date','-created_at']


class CampWorker(models.Model):
    ROLES=[('foreman','سرکارگر'),('mason','بنا'),('laborer','کارگر ساده'),('guard','نگهبان'),('cook','آشپز'),('gardener','باغبان'),('driver','راننده'),('other','متفرقه')]
    STATUS=[('active','فعال'),('inactive','غیرفعال'),('temporary','موقت')]
    site=models.ForeignKey(CampSite,on_delete=models.CASCADE,related_name='workers')
    full_name=models.CharField(max_length=160)
    role=models.CharField(max_length=20,choices=ROLES)
    phone=models.CharField(max_length=30,blank=True)
    referral=models.CharField(max_length=140,blank=True)
    status=models.CharField(max_length=20,choices=STATUS,default='active')
    daily_wage=models.DecimalField(max_digits=14,decimal_places=0,default=0)
    notes=models.TextField(blank=True)
    photo=models.ImageField(upload_to='camp/workers/',null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['full_name']
    def __str__(self): return self.full_name


class CampWorkerAttendance(models.Model):
    worker=models.ForeignKey(CampWorker,on_delete=models.CASCADE,related_name='attendance')
    date=models.DateField(default=timezone.localdate)
    is_present=models.BooleanField(default=True)
    start_time=models.TimeField(null=True,blank=True)
    end_time=models.TimeField(null=True,blank=True)
    work_done=models.TextField(blank=True)
    wage_for_day=models.DecimalField(max_digits=14,decimal_places=0,default=0)
    notes=models.TextField(blank=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='camp_worker_attendance')
    class Meta:
        ordering=['-date','worker__full_name']
        constraints=[models.UniqueConstraint(fields=['worker','date'],name='uniq_camp_worker_attendance')]


class CampProject(models.Model):
    STATUS=[('active','فعال'),('paused','متوقف'),('done','تمام‌شده')]
    site=models.ForeignKey(CampSite,on_delete=models.CASCADE,related_name='projects')
    name=models.CharField(max_length=180)
    manager=models.CharField(max_length=140,blank=True)
    start_date=models.DateField()
    status=models.CharField(max_length=20,choices=STATUS,default='active')
    progress=models.PositiveSmallIntegerField(default=0)
    estimated_cost=models.DecimalField(max_digits=16,decimal_places=0,default=0)
    actual_cost=models.DecimalField(max_digits=16,decimal_places=0,default=0)
    description=models.TextField(blank=True)
    blockers=models.TextField(blank=True)
    last_progress_date=models.DateField(null=True,blank=True)
    before_photo=models.ImageField(upload_to='camp/projects/before/',null=True,blank=True)
    during_photo=models.ImageField(upload_to='camp/projects/during/',null=True,blank=True)
    after_photo=models.ImageField(upload_to='camp/projects/after/',null=True,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['status','name']
    @property
    def over_budget(self): return self.estimated_cost and self.actual_cost > self.estimated_cost


class CampDailyTask(models.Model):
    PRIORITY=[('normal','عادی'),('important','مهم'),('urgent','فوری')]
    STATUS=[('todo','انجام نشده'),('doing','در حال انجام'),('done','انجام شده'),('stopped','متوقف شده')]
    site=models.ForeignKey(CampSite,on_delete=models.CASCADE,related_name='daily_tasks')
    date=models.DateField(default=timezone.localdate)
    title=models.CharField(max_length=180)
    responsible=models.CharField(max_length=140,blank=True)
    priority=models.CharField(max_length=20,choices=PRIORITY,default='normal')
    project=models.ForeignKey(CampProject,on_delete=models.SET_NULL,null=True,blank=True,related_name='tasks')
    status=models.CharField(max_length=20,choices=STATUS,default='todo')
    description=models.TextField(blank=True)
    before_photo=models.ImageField(upload_to='camp/tasks/before/',null=True,blank=True)
    after_photo=models.ImageField(upload_to='camp/tasks/after/',null=True,blank=True)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='camp_tasks_created')
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-date','priority','status']


class CampFoodPlan(models.Model):
    site=models.ForeignKey(CampSite,on_delete=models.CASCADE,related_name='food_plans')
    date=models.DateField()
    meal=models.CharField(max_length=160)
    people_count=models.PositiveIntegerField(default=0)
    ingredients=models.TextField(blank=True)
    estimated_cost=models.DecimalField(max_digits=14,decimal_places=0,default=0)
    actual_cost=models.DecimalField(max_digits=14,decimal_places=0,default=0)
    responsible=models.CharField(max_length=140,blank=True)
    notes=models.TextField(blank=True)
    class Meta:
        ordering=['date']
        constraints=[models.UniqueConstraint(fields=['site','date'],name='uniq_camp_food_date')]


class CampDailyPhoto(models.Model):
    TYPES=[('project','پروژه فعال'),('work','کار انجام‌شده'),('site','محوطه کمپ'),('purchase','خرید/فاکتور'),('inventory','انبار'),('other','سایر')]
    site=models.ForeignKey(CampSite,on_delete=models.CASCADE,related_name='daily_photos')
    date=models.DateField(default=timezone.localdate)
    photo_type=models.CharField(max_length=20,choices=TYPES)
    image=models.ImageField(upload_to='camp/daily/%Y/%m/%d/')
    uploader=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='camp_daily_photos')
    project=models.ForeignKey(CampProject,on_delete=models.SET_NULL,null=True,blank=True,related_name='daily_photos')
    caption=models.CharField(max_length=220,blank=True)
    location=models.CharField(max_length=140,blank=True)
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta: ordering=['-date','-created_at']


class CampCommanderCheck(models.Model):
    PERIOD=[('morning','Morning Check'),('night','Night Check')]
    site=models.ForeignKey(CampSite,on_delete=models.CASCADE,related_name='commander_checks')
    date=models.DateField(default=timezone.localdate)
    period=models.CharField(max_length=10,choices=PERIOD)
    answers=models.JSONField(default=dict)
    created_by=models.ForeignKey(User,on_delete=models.SET_NULL,null=True,blank=True,related_name='camp_commander_checks')
    created_at=models.DateTimeField(auto_now_add=True)
    updated_at=models.DateTimeField(auto_now=True)
    class Meta:
        constraints=[models.UniqueConstraint(fields=['site','date','period'],name='uniq_camp_commander_check')]
