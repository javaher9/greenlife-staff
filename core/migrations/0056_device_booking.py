from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


def seed_device_types(apps,schema_editor):
    DeviceType=apps.get_model('core','DeviceTypeSchedule')
    defaults=[
        ('Cryo70','کرایو',70,20),('DIF70','دیفاین',70,30),
        ('RS60','RS',60,20),('MED60','MED',60,20),
        ('EX60','EX',60,20),('Rema60','Rema',60,20),
        ('GL30','GL',30,30),('HAL30','HAL',30,30),
        ('Body30','Body',30,30),('EM30','EM',30,30),
    ]
    for code,name,treatment,prep in defaults:
        DeviceType.objects.get_or_create(
            code=code,defaults={'name':name,'treatment_minutes':treatment,'preparation_minutes':prep}
        )


class Migration(migrations.Migration):
    dependencies=[
        ('core','0055_device_tariff_partial_payments'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations=[
        migrations.AddField(
            model_name='consultationplanitem',
            name='units_per_session',
            field=models.PositiveSmallIntegerField(default=1),
        ),
        migrations.CreateModel(
            name='DeviceTypeSchedule',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('code',models.CharField(max_length=24,unique=True)),
                ('name',models.CharField(max_length=100)),
                ('treatment_minutes',models.PositiveSmallIntegerField(default=60)),
                ('preparation_minutes',models.PositiveSmallIntegerField(default=20)),
                ('is_active',models.BooleanField(default=True)),
            ],
            options={'ordering':['code']},
        ),
        migrations.CreateModel(
            name='DeviceCabin',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('name',models.CharField(max_length=100)),
                ('is_active',models.BooleanField(default=True)),
                ('branch',models.ForeignKey(to='core.branch',on_delete=django.db.models.deletion.CASCADE,related_name='device_cabins')),
            ],
            options={'ordering':['name','id']},
        ),
        migrations.CreateModel(
            name='PhysicalDevice',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('name',models.CharField(max_length=100)),
                ('work_start',models.TimeField(default='08:30')),
                ('last_start',models.TimeField(default='17:30')),
                ('is_active',models.BooleanField(default=True)),
                ('branch',models.ForeignKey(to='core.branch',on_delete=django.db.models.deletion.CASCADE,related_name='physical_devices')),
                ('cabin',models.ForeignKey(to='core.devicecabin',on_delete=django.db.models.deletion.SET_NULL,null=True,blank=True,related_name='assigned_devices')),
                ('device_type',models.ForeignKey(to='core.devicetypeschedule',on_delete=django.db.models.deletion.PROTECT,related_name='physical_devices')),
            ],
            options={'ordering':['branch_id','name','id']},
        ),
        migrations.CreateModel(
            name='DeviceSessionBooking',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('starts_at',models.DateTimeField(db_index=True)),
                ('treatment_ends_at',models.DateTimeField()),
                ('blocked_until',models.DateTimeField(db_index=True)),
                ('treatment_minutes_snapshot',models.PositiveSmallIntegerField()),
                ('preparation_minutes_snapshot',models.PositiveSmallIntegerField()),
                ('status',models.CharField(max_length=12,choices=[('booked','رزرو شده'),('completed','انجام شد'),('cancelled','لغو شده')],default='booked',db_index=True)),
                ('confirmation_sent_at',models.DateTimeField(null=True,blank=True)),
                ('reminder_sent_at',models.DateTimeField(null=True,blank=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('appointment',models.ForeignKey(to='core.visitappointment',on_delete=django.db.models.deletion.PROTECT,related_name='device_sessions')),
                ('branch',models.ForeignKey(to='core.branch',on_delete=django.db.models.deletion.PROTECT,related_name='device_session_bookings')),
                ('cabin',models.ForeignKey(to='core.devicecabin',on_delete=django.db.models.deletion.PROTECT,related_name='device_sessions')),
                ('device',models.ForeignKey(to='core.physicaldevice',on_delete=django.db.models.deletion.PROTECT,related_name='primary_device_sessions')),
                ('secondary_device',models.ForeignKey(to='core.physicaldevice',on_delete=django.db.models.deletion.PROTECT,null=True,blank=True,related_name='secondary_device_sessions')),
                ('plan_item',models.ForeignKey(to='core.consultationplanitem',on_delete=django.db.models.deletion.PROTECT,related_name='device_sessions')),
                ('created_by',models.ForeignKey(to=settings.AUTH_USER_MODEL,on_delete=django.db.models.deletion.SET_NULL,null=True,blank=True,related_name='created_device_sessions')),
            ],
            options={'ordering':['starts_at','id']},
        ),
        migrations.AddConstraint(
            model_name='devicecabin',
            constraint=models.UniqueConstraint(fields=['branch','name'],name='uniq_branch_device_cabin_name'),
        ),
        migrations.AddConstraint(
            model_name='physicaldevice',
            constraint=models.UniqueConstraint(fields=['branch','name'],name='uniq_branch_physical_device_name'),
        ),
        migrations.AddIndex(
            model_name='devicesessionbooking',
            index=models.Index(fields=['branch','starts_at','blocked_until'],name='device_booking_branch_range'),
        ),
        migrations.RunPython(seed_device_types,migrations.RunPython.noop),
    ]
