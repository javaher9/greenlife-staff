import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0138_phone_call_rating'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AssistantCallQueue',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('assistant', models.CharField(
                    choices=[('yasaman', 'یاسمن'), ('camellia', 'کاملیا'), ('rose', 'رز')],
                    max_length=12, unique=True,
                )),
                ('paused', models.BooleanField(default=False)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name='AssistantCallJob',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('scheduled_for', models.DateTimeField()),
                ('status', models.CharField(
                    choices=[
                        ('queued', 'در صف'), ('retry', 'در انتظار تلاش مجدد'), ('completed', 'انجام شد'),
                        ('failed', 'ناموفق'), ('cancelled', 'لغو شد'),
                    ],
                    default='queued', max_length=12,
                )),
                ('attempts', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('consent_session', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE, related_name='assistant_call_job',
                    to='core.leadcallsession',
                )),
                ('created_by', models.ForeignKey(
                    null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL,
                )),
                ('lead', models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE, related_name='assistant_call_jobs',
                    to='core.referrallead',
                )),
                ('queue', models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT, related_name='jobs',
                    to='core.assistantcallqueue', to_field='assistant',
                )),
            ],
            options={
                'indexes': [models.Index(fields=['queue', 'status', 'scheduled_for'], name='asst_job_queue_due_idx')],
                'constraints': [models.UniqueConstraint(
                    condition=models.Q(status__in=('queued', 'retry')),
                    fields=('lead',), name='one_open_assistant_job_per_lead',
                )],
            },
        ),
    ]
