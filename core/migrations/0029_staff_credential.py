from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[
        ('core','0028_set_hosni_foroughesh_receptionist'),
    ]

    operations=[
        migrations.CreateModel(
            name='StaffCredential',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('mobile_pin_hash',models.CharField(blank=True,max_length=128)),
                ('mobile_pin_cipher',models.TextField(blank=True)),
                ('desktop_password_cipher',models.TextField(blank=True)),
                ('mobile_pin_set_at',models.DateTimeField(blank=True,null=True)),
                ('desktop_password_set_at',models.DateTimeField(blank=True,null=True)),
                ('last_mobile_login',models.DateTimeField(blank=True,null=True)),
                ('last_desktop_login',models.DateTimeField(blank=True,null=True)),
                ('mobile_failed_attempts',models.PositiveSmallIntegerField(default=0)),
                ('mobile_locked_until',models.DateTimeField(blank=True,null=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('updated_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='updated_staff_credentials',to=settings.AUTH_USER_MODEL)),
                ('user',models.OneToOneField(on_delete=django.db.models.deletion.CASCADE,related_name='staff_credential',to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['user__last_name','user__first_name','user__username']},
        ),
    ]
