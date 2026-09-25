from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0048_add_link_payment_method'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterField(
            model_name='employeeprofile',
            name='role',
            field=models.CharField(
                choices=[
                    ('admin','مدیر سیستم'),
                    ('internal_manager','مدیر داخلی'),
                    ('manager','مدیر شعبه'),
                    ('referral_supervisor','ناظر شبکه فروش'),
                    ('call_center','کال‌سنتر'),
                    ('consultant','مشاور'),
                    ('doctor','پزشک'),
                    ('receptionist','منشی'),
                    ('employee','کارمند'),
                    ('referrer','معرف مشتری'),
                ],
                default='employee',
                max_length=20,
            ),
        ),
        migrations.CreateModel(
            name='PatientProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('full_name', models.CharField(max_length=140)),
                ('phone', models.CharField(db_index=True, max_length=30, unique=True)),
                ('photo', models.ImageField(blank=True, null=True, upload_to='patients/photos/%Y/%m/')),
                ('birth_date', models.DateField(blank=True, null=True)),
                ('sex', models.CharField(blank=True, choices=[('female','زن'),('male','مرد'),('other','سایر')], max_length=10)),
                ('height_cm', models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True)),
                ('neighborhood', models.CharField(blank=True, max_length=120)),
                ('address_summary', models.CharField(blank=True, max_length=220)),
                ('medical_history', models.TextField(blank=True)),
                ('is_vip', models.BooleanField(db_index=True, default=False)),
                ('crm_id', models.CharField(blank=True, db_index=True, max_length=120, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_patient_profiles', to=settings.AUTH_USER_MODEL)),
                ('home_branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='patients', to='core.branch')),
            ],
            options={'ordering':['full_name','id']},
        ),
        migrations.CreateModel(
            name='BodyAnalysisRecord',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('recorded_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('weight_kg', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('visceral_fat', models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True)),
                ('inbody_score', models.DecimalField(blank=True, decimal_places=1, max_digits=5, null=True)),
                ('skeletal_muscle_kg', models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True)),
                ('body_fat_percent', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('bmi', models.DecimalField(blank=True, decimal_places=2, max_digits=5, null=True)),
                ('measurements', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='body_analyses', to='core.patientprofile')),
                ('recorded_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='recorded_body_analyses', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['recorded_at','id']},
        ),
        migrations.CreateModel(
            name='PatientCareNote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('note_type', models.CharField(choices=[('cem','CEM'),('clinical','پزشکی'),('staff','یادداشت تیم')], db_index=True, default='staff', max_length=20)),
                ('body', models.TextField(max_length=3000)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('author', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='patient_care_notes', to=settings.AUTH_USER_MODEL)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='care_notes', to='core.patientprofile')),
            ],
            options={'ordering':['-created_at','-id']},
        ),
        migrations.CreateModel(
            name='PatientDietProgram',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('diet_name', models.CharField(max_length=160)),
                ('recommendation_pack', models.CharField(blank=True, max_length=160)),
                ('print_template', models.CharField(blank=True, max_length=160)),
                ('note', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('active','در حال اجرا'),('completed','تکمیل شده'),('paused','متوقف شده')], db_index=True, default='active', max_length=20)),
                ('prescribed_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='diet_programs', to='core.patientprofile')),
                ('prescribed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='prescribed_diet_programs', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-prescribed_at','-id']},
        ),
        migrations.CreateModel(
            name='PatientDeviceProgram',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('device_name', models.CharField(max_length=160)),
                ('area', models.CharField(blank=True, max_length=120)),
                ('sessions_prescribed', models.PositiveSmallIntegerField(default=1)),
                ('sessions_completed', models.PositiveSmallIntegerField(default=0)),
                ('note', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('planned','پیشنهاد شده'),('active','در حال انجام'),('completed','تکمیل شده'),('cancelled','لغو شده')], db_index=True, default='planned', max_length=20)),
                ('prescribed_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='device_programs', to='core.patientprofile')),
                ('prescribed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='prescribed_device_programs', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-prescribed_at','-id']},
        ),
        migrations.CreateModel(
            name='PatientLipolyticProgram',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('protocol_name', models.CharField(default='لیپولیتیک', max_length=160)),
                ('area', models.CharField(blank=True, max_length=120)),
                ('sessions_prescribed', models.PositiveSmallIntegerField(default=1)),
                ('sessions_completed', models.PositiveSmallIntegerField(default=0)),
                ('note', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('planned','پیشنهاد شده'),('active','در حال انجام'),('completed','تکمیل شده'),('cancelled','لغو شده')], db_index=True, default='planned', max_length=20)),
                ('prescribed_at', models.DateTimeField(default=django.utils.timezone.now)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lipolytic_programs', to='core.patientprofile')),
                ('prescribed_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='prescribed_lipolytic_programs', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['-prescribed_at','-id']},
        ),
    ]
