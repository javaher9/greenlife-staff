from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[('core','0032_weekly_work_schedules')]

    operations=[
        migrations.AddField(
            model_name='financialtransaction',name='appointment',
            field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.PROTECT,related_name='financial_transactions',to='core.visitappointment'),
        ),
        migrations.AddField(
            model_name='financialtransaction',name='sale_origin',
            field=models.CharField(blank=True,choices=[('afsariyeh','فروش افسریه'),('branch_walk_in','مراجعه مستقیم شعبه')],max_length=30),
        ),
        migrations.AddField(
            model_name='financialtransaction',name='sale_reason',
            field=models.CharField(blank=True,choices=[('device_package','پکیج دستگاه'),('daya_package','پکیج دایا'),('lipolytic','لیپولیتیک'),('skin','پوست'),('other','سایر')],max_length=30),
        ),
        migrations.AddConstraint(
            model_name='financialtransaction',
            constraint=models.UniqueConstraint(condition=models.Q(('appointment__isnull',False)),fields=('appointment',),name='uniq_finance_appointment'),
        ),
    ]
