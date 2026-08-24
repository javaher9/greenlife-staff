from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies=[('core','0013_shift_groups')]
    operations=[
        migrations.AddField(model_name='dailyreport',name='manager_comment',field=models.CharField(blank=True,max_length=300)),
        migrations.AddField(model_name='dailyreport',name='manager_comment_at',field=models.DateTimeField(blank=True,null=True)),
        migrations.AddField(model_name='dailyreport',name='manager_comment_by',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='report_comments',to='auth.user')),
        migrations.CreateModel(
            name='JobDutyTemplate',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('title',models.CharField(max_length=140)),
                ('job_title',models.CharField(blank=True,help_text='اگر خالی باشد برای همه سمت‌ها قابل استفاده است.',max_length=120)),
                ('description',models.TextField()),
                ('is_active',models.BooleanField(default=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('branch',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='job_duties',to='core.branch')),
                ('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_job_duties',to='auth.user')),
            ],
        ),
        migrations.CreateModel(
            name='Guideline',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('title',models.CharField(max_length=160)),
                ('body',models.TextField()),
                ('audience',models.CharField(choices=[('all','همه پرسنل'),('branch','یک شعبه'),('job','یک سمت شغلی')],default='all',max_length=20)),
                ('job_title',models.CharField(blank=True,max_length=120)),
                ('is_required',models.BooleanField(default=True)),
                ('is_active',models.BooleanField(default=True)),
                ('published_at',models.DateTimeField(auto_now_add=True)),
                ('branch',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='guidelines',to='core.branch')),
                ('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_guidelines',to='auth.user')),
            ],
        ),
        migrations.CreateModel(
            name='GuidelineAcknowledgement',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('acknowledged_at',models.DateTimeField(auto_now_add=True)),
                ('guideline',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='acknowledgements',to='core.guideline')),
                ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='guideline_acknowledgements',to='auth.user')),
            ],
        ),
        migrations.AddConstraint(model_name='guidelineacknowledgement',constraint=models.UniqueConstraint(fields=('guideline','user'),name='uniq_guideline_ack')),
    ]
