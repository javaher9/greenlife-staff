from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

class Migration(migrations.Migration):
    dependencies=[('core','0003_attendance')]
    operations=[
        migrations.AddField(model_name='branch',name='work_start',field=models.TimeField(default='09:00')),
        migrations.AddField(model_name='branch',name='work_end',field=models.TimeField(default='17:00')),
        migrations.AddField(model_name='branch',name='grace_minutes',field=models.PositiveSmallIntegerField(default=15)),
        migrations.CreateModel(name='ScoreEvent',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('points',models.IntegerField(default=0)),('reason',models.CharField(choices=[('attendance','حضور به‌موقع'),('task','انجام وظیفه'),('report','گزارش روزانه'),('kpi','امتیاز KPI'),('bonus','امتیاز تشویقی'),('penalty','کسر امتیاز')],default='bonus',max_length=20)),('description',models.CharField(blank=True,max_length=250)),('event_date',models.DateField(default=django.utils.timezone.localdate)),('created_at',models.DateTimeField(auto_now_add=True)),
            ('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_score_events',to='auth.user')),('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='score_events',to='auth.user'))],options={'ordering':['-event_date','-created_at']}),
        migrations.CreateModel(name='KPIRecord',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('title',models.CharField(max_length=120)),('value',models.DecimalField(decimal_places=2,max_digits=10)),('target',models.DecimalField(blank=True,decimal_places=2,max_digits=10,null=True)),('score',models.PositiveSmallIntegerField(default=0,help_text='امتیاز از ۰ تا ۱۰۰')),('period_start',models.DateField()),('period_end',models.DateField()),('note',models.TextField(blank=True)),('created_at',models.DateTimeField(auto_now_add=True)),('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_kpi_records',to='auth.user')),('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='kpi_records',to='auth.user'))],options={'ordering':['-period_end','-created_at']})]
