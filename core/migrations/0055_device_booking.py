from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone

DEFAULTS=[
    ('Cryo70','Cryo70',70,20),('DIF70','DIF70',70,30),
    ('RS60','RS60',60,20),('MED60','MED60',60,20),
    ('EX60','EX60',60,20),('Rema60','Rema60',60,20),
    ('GL30','GL30',30,30),('HAL30','HAL30',30,30),
    ('Body30','Body30',30,30),('EM30','EM30',30,30),
]

def seed_device_kinds(apps,schema_editor):
    Kind=apps.get_model('core','DeviceKind')
    for code,label,treat,prepare in DEFAULTS:
        Kind.objects.get_or_create(
            code=code,
            defaults=dict(label=label,treatment_minutes=treat,
                          preparation_minutes=prepare,work_start='08:30',
                          last_start='17:30',is_active=True),
        )

class Migration(migrations.Migration):
    dependencies=[
        ('core','0054_device_tariff_partial_payments'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]
    operations=[
        migrations.CreateModel(
            name='DeviceKind',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('code',models.CharField(max_length=24,unique=True)),
                ('label',models.CharField(max_length=100)),
                ('treatment_minutes',models.PositiveSmallIntegerField(default=70)),
                ('preparation_minutes',models.PositiveSmallIntegerField(default=20)),
                ('work_start',models.TimeField(default='08:30')),
                ('last_start',models.TimeField(default='17:30')),
                ('is_active',models.BooleanField(default=True)),
            ],
        ),
        migrations.CreateModel(
            name='DeviceCabin',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('name',models.CharField(max_length=110)),
                ('is_active',models.BooleanField(default=True)),
                ('branch',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='device_cabins',to='core.branch')),
            ],
            options={'ordering':['branch_id','name','id']},
        ),
        migrations.AddConstraint(
            model_name='devicecabin',
            constraint=models.UniqueConstraint(fields=('branch','name'),name='uniq_device_cabin_branch_name'),
        ),
        migrations.CreateModel(
            name='DeviceUnit',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('name',models.CharField(max_length=110)),
                ('treatment_override_min',models.PositiveSmallIntegerField(blank=True,null=True)),
                ('preparation_override_min',models.PositiveSmallIntegerField(blank=True,null=True)),
                ('work_start_override',models.TimeField(blank=True,null=True)),
                ('last_start_override',models.TimeField(blank=True,null=True)),
                ('is_active',models.BooleanField(default=True)),
                ('branch',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='device_units',to='core.branch')),
                ('home_cabin',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='home_devices',to='core.devicecabin')),
                ('kind',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='physical_units',to='core.devicekind')),
            ],
            options={'ordering':['branch_id','kind_id','name','id']},
        ),
        migrations.AddConstraint(
            model_name='deviceunit',
            constraint=models.UniqueConstraint(fields=('branch','name'),name='uniq_device_unit_branch_name'),
        ),
        migrations.CreateModel(
            name='DeviceBooking',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('day',models.DateField(db_index=True)),
                ('starts_at',models.DateTimeField(db_index=True)),
                ('ends_at',models.DateTimeField(db_index=True)),
                ('treatment_minutes_snapshot',models.PositiveSmallIntegerField()),
                ('preparation_minutes_snapshot',models.PositiveSmallIntegerField()),
                ('status',models.CharField(choices=[('booked','رزرو شده'),('completed','انجام شد'),('cancelled','لغو شده')],db_index=True,default='booked',max_length=16)),
                ('confirmation_sent_at',models.DateTimeField(blank=True,null=True)),
                ('reminder_sent_at',models.DateTimeField(blank=True,null=True)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('updated_at',models.DateTimeField(auto_now=True)),
                ('appointment',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='device_bookings',to='core.visitappointment')),
                ('branch',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='device_bookings',to='core.branch')),
                ('cabin',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='bookings',to='core.devicecabin')),
                ('created_by',models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='created_device_bookings',to=settings.AUTH_USER_MODEL)),
                ('kind',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='bookings',to='core.devicekind')),
                ('plan_item',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='device_bookings',to='core.consultationplanitem')),
            ],
            options={'ordering':['starts_at','id'],'indexes':[models.Index(fields=['branch','day','status'],name='devicebook_branch_day_idx')]},
        ),
        migrations.CreateModel(
            name='DeviceBookingUnit',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('booking',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='reserved_units',to='core.devicebooking')),
                ('unit',models.ForeignKey(on_delete=django.db.models.deletion.PROTECT,related_name='reservations',to='core.deviceunit')),
            ],
        ),
        migrations.AddConstraint(
            model_name='devicebookingunit',
            constraint=models.UniqueConstraint(fields=('booking','unit'),name='uniq_device_booking_unit'),
        ),
        migrations.AddField(
            model_name='devicebooking',
            name='units',
            field=models.ManyToManyField(related_name='device_bookings',through='core.DeviceBookingUnit',to='core.deviceunit'),
        ),
        migrations.RunPython(seed_device_kinds,migrations.RunPython.noop),
    ]
