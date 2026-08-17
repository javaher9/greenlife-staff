from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('core','0004_shift_kpi_gamification')]
    operations=[
        migrations.CreateModel(name='IntegrationSyncLog',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('provider',models.CharField(default='crm',max_length=30)),('status',models.CharField(choices=[('ok','موفق'),('error','خطا')],max_length=10)),('imported',models.PositiveIntegerField(default=0)),('updated',models.PositiveIntegerField(default=0)),('message',models.TextField(blank=True)),('started_at',models.DateTimeField()),('finished_at',models.DateTimeField(auto_now_add=True))],options={'ordering':['-finished_at']}),
        migrations.CreateModel(name='FinancialTransaction',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('external_id',models.CharField(blank=True,max_length=120,null=True)),('source',models.CharField(choices=[('crm','CRM'),('sheet','Google Sheet'),('manual','دستی')],default='crm',max_length=20)),('occurred_at',models.DateTimeField()),('amount',models.DecimalField(decimal_places=2,max_digits=18)),('payment_method',models.CharField(blank=True,max_length=80)),('service',models.CharField(blank=True,max_length=160)),('patient_ref',models.CharField(blank=True,max_length=120)),('raw_data',models.JSONField(blank=True,default=dict)),('synced_at',models.DateTimeField(auto_now=True)),('created_at',models.DateTimeField(auto_now_add=True)),('branch',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='financial_transactions',to='core.branch'))],options={'ordering':['-occurred_at']}),
        migrations.AddConstraint(model_name='financialtransaction',constraint=models.UniqueConstraint(condition=models.Q(('external_id__isnull',False)),fields=('source','external_id'),name='uniq_finance_source_external')),
    ]
