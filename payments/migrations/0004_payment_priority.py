from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies=[('payments','0003_classify_expenses')]
    operations=[migrations.AddField(model_name='paymentrequest',name='priority',field=models.CharField(choices=[('urgent','فوری'),('today','امروز'),('normal','عادی'),('low','کم‌اولویت')],db_index=True,default='normal',max_length=12)),migrations.AlterField(model_name='paymentrequest',name='channel',field=models.CharField(blank=True,choices=[('consultant','مشاور'),('accountant','حسابدار'),('staff','کارمند منتخب')],max_length=12))]
