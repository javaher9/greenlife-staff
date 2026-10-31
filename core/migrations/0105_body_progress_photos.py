from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import core.body_progress_models
import uuid


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0104_skin_care_share'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='BodyProgressPhoto',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('public_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('image', models.ImageField(upload_to=core.body_progress_models.progress_photo_path)),
                ('phase', models.CharField(choices=[('baseline', 'قبل از شروع'), ('followup', 'پیگیری')], max_length=12)),
                ('angle', models.CharField(choices=[('front', 'روبه‌رو'), ('side', 'نیم‌رخ'), ('back', 'پشت')], max_length=8)),
                ('taken_at', models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ('consent_recorded_at', models.DateTimeField()),
                ('is_visible', models.BooleanField(default=True)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='progress_photos', to='core.patientprofile')),
                ('scan', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='progress_photos', to='core.bodyanalysisrecord')),
                ('recorded_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='patient_progress_photos', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-taken_at', '-id']},
        ),
        migrations.AddIndex(
            model_name='bodyprogressphoto',
            index=models.Index(fields=['patient', 'taken_at'], name='body_photo_patient_day_idx'),
        ),
    ]
