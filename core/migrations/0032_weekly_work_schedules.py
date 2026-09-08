from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies=[('core','0031_internal_message'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]

    operations=[
        migrations.CreateModel(
            name='BranchWorkSchedule',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('weekday',models.PositiveSmallIntegerField(choices=[(0,'دوشنبه'),(1,'سه‌شنبه'),(2,'چهارشنبه'),(3,'پنجشنبه'),(4,'جمعه'),(5,'شنبه'),(6,'یکشنبه')])),
                ('is_working',models.BooleanField(default=True)),
                ('start_time',models.TimeField(blank=True,null=True)),
                ('end_time',models.TimeField(blank=True,null=True)),
                ('effective_from',models.DateField(db_index=True,default=django.utils.timezone.localdate)),
                ('effective_until',models.DateField(blank=True,db_index=True,null=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('branch',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='weekly_schedules',to='core.branch')),
                ('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_branch_work_schedules',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['branch__name','weekday','-effective_from']},
        ),
        migrations.CreateModel(
            name='EmployeeWorkSchedule',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('weekday',models.PositiveSmallIntegerField(choices=[(0,'دوشنبه'),(1,'سه‌شنبه'),(2,'چهارشنبه'),(3,'پنجشنبه'),(4,'جمعه'),(5,'شنبه'),(6,'یکشنبه')])),
                ('is_working',models.BooleanField(default=True)),
                ('start_time',models.TimeField(blank=True,null=True)),
                ('end_time',models.TimeField(blank=True,null=True)),
                ('effective_from',models.DateField(db_index=True,default=django.utils.timezone.localdate)),
                ('effective_until',models.DateField(blank=True,db_index=True,null=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_employee_work_schedules',to=settings.AUTH_USER_MODEL)),
                ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='weekly_work_schedules',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['user__last_name','user__first_name','weekday','-effective_from']},
        ),
        migrations.AddConstraint(model_name='branchworkschedule',constraint=models.UniqueConstraint(fields=('branch','weekday','effective_from'),name='uniq_branch_weekday_effective')),
        migrations.AddConstraint(model_name='employeeworkschedule',constraint=models.UniqueConstraint(fields=('user','weekday','effective_from'),name='uniq_employee_weekday_effective')),
        migrations.AddIndex(model_name='branchworkschedule',index=models.Index(fields=['branch','weekday','effective_from'],name='branch_weekday_effect_idx')),
        migrations.AddIndex(model_name='employeeworkschedule',index=models.Index(fields=['user','weekday','effective_from'],name='employee_weekday_effect_idx')),
    ]
