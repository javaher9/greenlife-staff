from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    initial = True
    dependencies = [('core', '__first__'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(
            name='IntakeInvitation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('expires_at', models.DateTimeField()),
                ('sent_at', models.DateTimeField(blank=True, null=True)),
                ('completed_at', models.DateTimeField(blank=True, null=True)),
                ('started_at', models.DateTimeField(blank=True, null=True)),
                ('answers', models.JSONField(blank=True, default=dict)),
                ('consent_version', models.CharField(blank=True, max_length=20)),
                ('consent_at', models.DateTimeField(blank=True, null=True)),
                ('sms_status', models.CharField(default='pending', max_length=20)),
                ('appointment', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='intake_invitation', to='core.visitappointment')),
                ('sent_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-id']},
        ),
    ]
