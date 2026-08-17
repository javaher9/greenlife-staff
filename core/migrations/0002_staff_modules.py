from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
class Migration(migrations.Migration):
    dependencies=[('core','0001_initial'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.AddField(model_name='employeeprofile',name='avatar',field=models.ImageField(blank=True,null=True,upload_to='avatars/')),
        migrations.AddField(model_name='employeeprofile',name='is_active',field=models.BooleanField(default=True)),
        migrations.AddField(model_name='employeeprofile',name='phone',field=models.CharField(blank=True,max_length=30)),
        migrations.AddField(model_name='employeeprofile',name='start_date',field=models.DateField(blank=True,null=True)),
        migrations.AddField(model_name='task',name='updated_at',field=models.DateTimeField(auto_now=True)),
        migrations.AddField(model_name='announcement',name='created_by',field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to=settings.AUTH_USER_MODEL)),
        migrations.CreateModel(name='SOPDocument',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('title',models.CharField(max_length=200)),('description',models.TextField(blank=True)),('job_title',models.CharField(blank=True,max_length=120)),('file',models.FileField(blank=True,null=True,upload_to='sop/')),('content',models.TextField(blank=True)),('is_active',models.BooleanField(default=True)),('created_at',models.DateTimeField(auto_now_add=True)),('branch',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to='core.branch'))]),
        migrations.CreateModel(name='LeaveRequest',fields=[('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),('request_type',models.CharField(choices=[('annual','مرخصی استحقاقی'),('sick','مرخصی استعلاجی'),('hourly','مرخصی ساعتی'),('mission','ماموریت')],default='annual',max_length=20)),('start_date',models.DateField()),('end_date',models.DateField()),('reason',models.TextField(blank=True)),('status',models.CharField(choices=[('pending','در انتظار بررسی'),('approved','تایید شده'),('rejected','رد شده')],default='pending',max_length=20)),('manager_note',models.TextField(blank=True)),('created_at',models.DateTimeField(auto_now_add=True)),('reviewed_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='reviewed_leave_requests',to=settings.AUTH_USER_MODEL)),('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='leave_requests',to=settings.AUTH_USER_MODEL))]),
    ]
