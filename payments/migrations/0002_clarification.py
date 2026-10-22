from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('payments','0001_initial'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.AddField(model_name='paymentrequest',name='clarification_assignee',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='payment_clarifications',to=settings.AUTH_USER_MODEL)),
        migrations.AlterField(model_name='paymentrequest',name='state',field=models.CharField(max_length=12,choices=[('pending','در انتظار تأیید'),('approved','در صف پرداخت'),('rejected','رد شده'),('needs_info','نیازمند توضیح بیشتر'),('paid','پرداخت شده')],default='pending',db_index=True)),
        migrations.CreateModel(name='PaymentClarification',fields=[
            ('id',models.BigAutoField(primary_key=True,serialize=False)),
            ('message',models.TextField()),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('author',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to=settings.AUTH_USER_MODEL)),
            ('payment',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='clarifications',to='payments.paymentrequest'))],
            options={'ordering':['created_at']}),
    ]
