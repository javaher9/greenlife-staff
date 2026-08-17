from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

class Migration(migrations.Migration):
    dependencies=[('core','0002_staff_modules'),migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations=[
        migrations.CreateModel(
            name='Attendance',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('date',models.DateField(default=django.utils.timezone.localdate)),
                ('check_in',models.DateTimeField(blank=True,null=True)),
                ('check_out',models.DateTimeField(blank=True,null=True)),
                ('status',models.CharField(choices=[('present','حاضر'),('late','تاخیر'),('absent','غایب'),('leave','مرخصی')],default='present',max_length=12)),
                ('note',models.CharField(blank=True,max_length=250)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('branch',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to='core.branch')),
                ('user',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='attendance_records',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-date','user__last_name']},
        ),
        migrations.AddConstraint(model_name='attendance',constraint=models.UniqueConstraint(fields=('user','date'),name='uniq_attendance_user_date')),
    ]
