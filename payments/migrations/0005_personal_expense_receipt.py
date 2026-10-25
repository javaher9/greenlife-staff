from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies=[('payments','0004_payment_priority')]
    operations=[
        migrations.AlterField(model_name='paymentrequest',name='kind',field=models.CharField(max_length=16,choices=[('payment','درخواست پرداخت'),('petty_cash','درخواست تنخواه'),('personal_expense','هزینه پرداخت‌شده از حساب شخصی')])),
        migrations.AddField(model_name='paymentrequest',name='personal_expense_receipt',field=models.FileField(upload_to='personal_expenses/%Y/%m/',blank=True)),
    ]
