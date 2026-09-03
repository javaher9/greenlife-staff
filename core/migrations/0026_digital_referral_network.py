from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0025_meeting_minutes'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='DigitalReferralProfile',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('source', models.CharField(choices=[('instagram', 'Instagram'), ('greenlife', 'GreenLifeClinics.com'), ('drjavaherian', 'DrJavaherian.com'), ('rejim', 'Rejim.ir'), ('other', 'سایر')], db_index=True, max_length=24)),
                ('source_detail', models.CharField(blank=True, max_length=120)),
                ('phone', models.CharField(db_index=True, max_length=30)),
                ('photo', models.ImageField(blank=True, null=True, upload_to='digital-referrals/people/%Y/%m/')),
                ('referral_code', models.CharField(db_index=True, max_length=24, unique=True)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('sponsor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='members', to='core.digitalreferralprofile')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='digital_referral_profile', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.CreateModel(
            name='DigitalReferralLead',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('full_name', models.CharField(max_length=140)),
                ('phone', models.CharField(db_index=True, max_length=30)),
                ('interested_service', models.CharField(blank=True, max_length=160)),
                ('notes', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('new', 'جدید'), ('contacted', 'تماس گرفته شد'), ('appointment', 'نوبت ثبت شد'), ('visited', 'مراجعه کرد'), ('won', 'فروش موفق'), ('lost', 'ناموفق')], db_index=True, default='new', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('assigned_to', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='assigned_digital_referral_leads', to='core.employeeprofile')),
                ('referrer', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='digital_leads', to='core.digitalreferralprofile')),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='digitalreferralprofile',
            index=models.Index(fields=['source', '-created_at'], name='digref_source_created_idx'),
        ),
        migrations.AddIndex(
            model_name='digitalreferrallead',
            index=models.Index(fields=['referrer', 'status', '-created_at'], name='diglead_ref_status_idx'),
        ),
    ]
