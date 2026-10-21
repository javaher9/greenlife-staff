from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.core.validators

class Migration(migrations.Migration):
    initial = True
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('core', '__first__'),
    ]
    operations = [
        migrations.CreateModel(
            name='PaymentRequest',
            fields=[
                ('id',models.BigAutoField(primary_key=True,serialize=False)),
                ('kind',models.CharField(max_length=16,choices=[('payment','درخواست پرداخت'),('petty_cash','درخواست تنخواه')])),
                ('amount_toman',models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('description',models.TextField()),
                ('recipient_name',models.CharField(max_length=160,blank=True)),
                ('recipient_iban',models.CharField(max_length=34,blank=True)),
                ('recipient_card',models.CharField(max_length=24,blank=True)),
                ('state',models.CharField(max_length=12,choices=[('pending','در انتظار تأیید'),('approved','در صف پرداخت'),('rejected','رد شده'),('paid','پرداخت شده')],default='pending',db_index=True)),
                ('channel',models.CharField(max_length=12,choices=[('consultant','مشاور'),('accountant','حسابدار')],blank=True)),
                ('approved_at',models.DateTimeField(null=True,blank=True)),
                ('payment_reference',models.CharField(max_length=120,blank=True)),
                ('payment_receipt',models.FileField(upload_to='payment_receipts/%Y/%m/',blank=True)),
                ('paid_at',models.DateTimeField(null=True,blank=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('branch',models.ForeignKey(to='core.branch',on_delete=django.db.models.deletion.PROTECT,null=True,blank=True)),
                ('requester',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.PROTECT,related_name='requested_payments')),
                ('beneficiary',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.PROTECT,null=True,blank=True,related_name='petty_cash_requests')),
                ('assigned_to',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.PROTECT,null=True,blank=True,related_name='assigned_payments')),
                ('approved_by',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.PROTECT,null=True,blank=True,related_name='approved_payments')),
            ],
            options={'ordering':['-created_at'],'permissions':[('execute_official_payment','May execute official bank payments')]},
        ),
        migrations.CreateModel(
            name='PettyCashExpense',
            fields=[
                ('id',models.BigAutoField(primary_key=True,serialize=False)),
                ('amount_toman',models.PositiveBigIntegerField(validators=[django.core.validators.MinValueValidator(1)])),
                ('description',models.TextField()),
                ('receipt',models.FileField(upload_to='petty_expenses/%Y/%m/')),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('holder',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.PROTECT,related_name='petty_expenses')),
                ('created_by',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.PROTECT,related_name='recorded_petty_expenses')),
            ],
        ),
        migrations.CreateModel(
            name='PaymentEvent',
            fields=[
                ('id',models.BigAutoField(primary_key=True,serialize=False)),
                ('action',models.CharField(max_length=30)),
                ('notes',models.CharField(max_length=250,blank=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('actor',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.PROTECT)),
                ('payment',models.ForeignKey(to='payments.paymentrequest',on_delete=django.db.models.deletion.PROTECT,related_name='events')),
            ],
            options={'ordering':['created_at']},
        ),
        migrations.AddIndex(model_name='paymentrequest',index=models.Index(fields=['assigned_to','state'],name='payments_pa_assigne_2b467e_idx')),
    ]
