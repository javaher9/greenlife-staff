from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator

class PaymentRequest(models.Model):
    TYPES = [('payment','درخواست پرداخت'),('petty_cash','درخواست تنخواه')]
    STATES = [('pending','در انتظار تأیید'),('approved','در صف پرداخت'),('rejected','رد شده'),('paid','پرداخت شده')]
    CHANNELS = [('consultant','مشاور'),('accountant','حسابدار')]
    kind = models.CharField(max_length=16,choices=TYPES)
    amount_toman = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    description = models.TextField()
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
    approved_at = models.DateTimeField(null=True,blank=True)
    payment_reference = models.CharField(max_length=120,blank=True)
    payment_receipt = models.FileField(upload_to='payment_receipts/%Y/%m/',blank=True)
    paid_at = models.DateTimeField(null=True,blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['assigned_to','state'])]
        permissions = [('execute_official_payment','May execute official bank payments')]
class PettyCashExpense(models.Model):
    holder = models.ForeignKey(settings.AUTH_USER_MODEL,on_delete=models.PROTECT,related_name='petty_expenses')
    amount_toman = models.PositiveBigIntegerField(validators=[MinValueValidator(1)])
    description = models.TextField()
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
