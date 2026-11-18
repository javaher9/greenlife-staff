from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator


EXPENSE_CATEGORIES = [
    ('unspecified', 'دسته‌بندی‌نشده'),
    ('legal', 'وکیل و امور حقوقی'),
    ('salaries', 'حقوق و مزایا'),
    ('commission', 'پورسانت'),
    ('advertising', 'تبلیغات و بازاریابی'),
    ('equipment', 'تجهیزات و دستگاه‌ها'),
    ('supplies', 'خرید و ملزومات'),
    ('rent', 'اجاره و ساختمان'),
    ('utilities', 'آب، برق و خدمات'),
    ('transport', 'حمل‌ونقل و سفر'),
    ('projects', 'پروژه و سرمایه‌گذاری'),
    ('personal', 'هزینه شخصی'),
    ('other', 'سایر'),
]
COST_OWNERS = [
    ('unspecified', 'تعیین‌نشده'),
    ('company', 'شرکت'),
    ('personal', 'شخصی مدیر'),
    ('project', 'پروژه'),
    ('other', 'سایر / خارج از شرکت'),
]


class ActivePaymentRequestManager(models.Manager):
    """Keep removed requests out of every operational queue and total."""

    def get_queryset(self):
        return super().get_queryset().filter(deleted_at__isnull=True)


class PaymentRequest(models.Model):
    TYPES = [('payment','درخواست پرداخت'),('petty_cash','درخواست تنخواه'),('personal_expense','هزینه پرداخت‌شده از حساب شخصی')]
    STATES = [('pending','در انتظار تأیید'),('approved','در صف پرداخت'),('rejected','رد شده'),('needs_info','نیازمند توضیح بیشتر'),('paid','پرداخت شده')]
    CHANNELS = [('consultant','مشاور'),('accountant','حسابدار'),('staff','کارمند منتخب')]
    PRIORITIES = [('urgent','فوری'),('today','امروز'),('normal','عادی'),('low','کم‌اولویت')]
    PAYMENT_METHODS = [
        ('smartpay', 'SmartPay'), ('bank_transfer', 'حواله بانکی'),
        ('card_to_card', 'کارت‌به‌کارت'), ('pos', 'کارت‌خوان'),
        ('cash', 'نقدی'), ('other', 'سایر'),
    ]
    FUNDING_SOURCES = [
        ('personal', 'حساب شخصی مدیر'), ('company', 'حساب شرکت'),
        ('other', 'سایر حساب‌ها'),
    ]
    DELETION_REASONS = [
        ('duplicate', 'درخواست تکراری'),
        ('outdated', 'درخواست قدیمی و منتفی‌شده'),
        ('mistake', 'ثبت اشتباهی'),
    ]
    kind = models.CharField(max_length=16,choices=TYPES)
    amount_toman = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    description = models.TextField()
    category = models.CharField(max_length=24, choices=EXPENSE_CATEGORIES, default='unspecified', db_index=True)
    cost_owner = models.CharField(max_length=20, choices=COST_OWNERS, default='unspecified', db_index=True)
    cost_center = models.CharField(max_length=160, blank=True)
    due_date = models.DateField(null=True, blank=True)
    priority = models.CharField(max_length=12, choices=PRIORITIES, default='normal', db_index=True)
    recipient_name = models.CharField(max_length=160,blank=True)
    recipient_iban = models.CharField(max_length=34,blank=True)
    recipient_card = models.CharField(max_length=24,blank=True)
    branch = models.ForeignKey('core.Branch',on_delete=models.PROTECT,null=True,blank=True)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='requested_payments')
    beneficiary = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='petty_cash_requests')
    state = models.CharField(max_length=12,choices=STATES,default='pending',db_index=True)
    channel = models.CharField(max_length=12,choices=CHANNELS,blank=True)
    assigned_to = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='assigned_payments')
    approved_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='approved_payments')
    clarification_assignee = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,null=True,blank=True,related_name='payment_clarifications')
    approved_at = models.DateTimeField(null=True,blank=True)
    # Filled at execution, not when the payment order is created.
    payment_method = models.CharField(max_length=24, choices=PAYMENT_METHODS, blank=True)
    funding_source = models.CharField(max_length=16, choices=FUNDING_SOURCES, blank=True)
    payment_reference = models.CharField(max_length=120,blank=True)
    payment_receipt = models.FileField(upload_to='payment_receipts/%Y/%m/',blank=True)
    personal_expense_receipt=models.FileField(upload_to='personal_expenses/%Y/%m/',blank=True)
    paid_at = models.DateTimeField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # Operational deletion preserves the audit trail without leaving an active
    # request in the requester, reviewer, or payment operator's workspace.
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
        related_name='deleted_payment_requests',
    )
    deletion_reason = models.CharField(max_length=16, choices=DELETION_REASONS, null=True, blank=True)

    objects = ActivePaymentRequestManager()
    all_objects = models.Manager()

    @property
    def has_payment_evidence(self):
        """A wrong state must not make a previously paid request removable."""
        if self.state == 'paid' or self.paid_at or self.payment_reference or self.payment_receipt:
            return True
        recorded = getattr(self, 'history_paid_event', None)
        if recorded is not None:
            return recorded
        return bool(self.pk and self.events.filter(action='paid').exists())

    class Meta:
        default_manager_name = 'objects'
        # Audit events must still resolve their parent after operational removal.
        base_manager_name = 'all_objects'
        ordering = ['-created_at']
        indexes = [models.Index(fields=['assigned_to','state'])]
        permissions = [('execute_official_payment','May execute official bank payments')]
class PettyCashExpense(models.Model):
    holder = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='petty_expenses')
    amount_toman = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    description = models.TextField()
    category = models.CharField(max_length=24, choices=EXPENSE_CATEGORIES, default='unspecified', db_index=True)
    cost_owner = models.CharField(max_length=20, choices=COST_OWNERS, default='unspecified', db_index=True)
    cost_center = models.CharField(max_length=160, blank=True)
    receipt = models.FileField(upload_to='petty_expenses/%Y/%m/')
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='recorded_petty_expenses')
    created_at = models.DateTimeField(auto_now_add=True)
class PaymentEvent(models.Model):
    payment = models.ForeignKey(PaymentRequest,on_delete=models.PROTECT,related_name='events')
    actor = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    action = models.CharField(max_length=30)
    notes = models.CharField(max_length=250,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['created_at']

class PaymentClarification(models.Model):
    payment=models.ForeignKey(PaymentRequest,on_delete=models.PROTECT,related_name='clarifications')
    author=models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT)
    message=models.TextField()
    created_at=models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering=['created_at']


class SavedPaymentRecipient(models.Model):
    """Private executive address book; no payment amount is stored."""
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_payment_recipients')
    name = models.CharField(max_length=160)
    iban = models.CharField(max_length=34, blank=True)
    card = models.CharField(max_length=24, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name', 'pk']
        indexes = [models.Index(fields=['owner', 'name'])]
