from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[('core','0094_marketing_worker_state')]
    operations=[
        migrations.CreateModel(name='CustomerPortalMember',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('phone',models.CharField(max_length=11,unique=True)),
            ('full_name',models.CharField(blank=True,max_length=140)),
            ('referral_code',models.CharField(max_length=24,unique=True)),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('last_login_at',models.DateTimeField(blank=True,null=True)),
        ]),
        migrations.CreateModel(name='CustomerPortalOTP',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('phone',models.CharField(max_length=11,unique=True)),
            ('code_hash',models.CharField(blank=True,max_length=128)),
            ('expires_at',models.DateTimeField(blank=True,null=True)),
            ('sent_at',models.DateTimeField(blank=True,null=True)),
            ('window_started_at',models.DateTimeField(blank=True,null=True)),
            ('sends_in_window',models.PositiveSmallIntegerField(default=0)),
            ('failed_attempts',models.PositiveSmallIntegerField(default=0)),
        ]),
        migrations.CreateModel(name='CustomerClubPolicy',fields=[
            ('id',models.PositiveSmallIntegerField(default=1,editable=False,primary_key=True,serialize=False)),
            ('enabled',models.BooleanField(default=False)),
            ('referral_points',models.PositiveIntegerField(default=0)),
            ('updated_at',models.DateTimeField(auto_now=True)),
            ('updated_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to='auth.user')),
        ]),
        migrations.CreateModel(name='CustomerClubReferral',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('status',models.CharField(choices=[('pending','منتظر تأیید مراجعه'),('qualified','تأیید شده')],default='pending',max_length=12)),
            ('qualified_at',models.DateTimeField(blank=True,null=True)),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('invited',models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,related_name='invitation',to='core.customerportalmember')),
            ('qualified_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to='auth.user')),
            ('referrer',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='invited_members',to='core.customerportalmember')),
        ],options={'ordering':['-created_at']}),
        migrations.CreateModel(name='CustomerClubPoints',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('amount',models.PositiveIntegerField()),
            ('created_at',models.DateTimeField(auto_now_add=True)),
            ('approved_by',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,to='auth.user')),
            ('member',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='points_entries',to='core.customerportalmember')),
            ('referral',models.OneToOneField(on_delete=django.db.models.deletion.PROTECT,related_name='points_entry',to='core.customerclubreferral')),
        ]),
        migrations.CreateModel(name='CustomerServiceRequest',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('kind',models.CharField(choices=[('visit','درخواست ویزیت'),('device','درخواست نوبت دستگاه')],max_length=12)),
            ('preferred_date',models.DateField(blank=True,null=True)),
            ('daypart',models.CharField(choices=[('any','فرقی ندارد'),('morning','صبح'),('afternoon','بعدازظهر')],default='any',max_length=12)),
            ('note',models.CharField(blank=True,max_length=300)),
            ('status',models.CharField(choices=[('pending','در انتظار بررسی'),('contacted','در حال پیگیری'),('booked','نوبت تأیید شد'),('declined','بسته شد')],db_index=True,default='pending',max_length=12)),
            ('staff_note',models.CharField(blank=True,max_length=300)),
            ('created_at',models.DateTimeField(auto_now_add=True,db_index=True)),
            ('updated_at',models.DateTimeField(auto_now=True)),
            ('assigned_to',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='customer_service_requests',to='core.employeeprofile')),
            ('branch',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='customer_requests',to='core.branch')),
            ('device_session',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to='core.devicesessionbooking')),
            ('member',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='requests',to='core.customerportalmember')),
            ('resolved_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to='auth.user')),
            ('visit_appointment',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,to='core.visitappointment')),
        ],options={'ordering':['-created_at','-id']}),
        migrations.AddConstraint(model_name='customerservicerequest',constraint=models.UniqueConstraint(condition=models.Q(status__in=('pending','contacted')),fields=('member','kind'),name='uniq_cust_open_kind')),
    ]
