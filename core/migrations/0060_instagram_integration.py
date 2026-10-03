from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0059_country_engine'),
    ]

    operations = [
        migrations.CreateModel(
            name='InstagramWebhookEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_hash', models.CharField(db_index=True, max_length=64, unique=True)),
                ('payload', models.JSONField(default=dict)),
                ('status', models.CharField(choices=[('received', 'دریافت شد'), ('processed', 'پردازش شد'), ('ignored', 'نادیده گرفته شد'), ('error', 'خطا')], db_index=True, default='received', max_length=12)),
                ('error', models.CharField(blank=True, max_length=500)),
                ('received_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={'ordering': ['-received_at', '-id']},
        ),
        migrations.CreateModel(
            name='InstagramIntegrationSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('app_id', models.CharField(blank=True, max_length=80)),
                ('app_secret_cipher', models.TextField(blank=True)),
                ('access_token_cipher', models.TextField(blank=True)),
                ('verify_token_cipher', models.TextField(blank=True)),
                ('instagram_user_id', models.CharField(blank=True, db_index=True, max_length=120)),
                ('username', models.CharField(blank=True, max_length=120)),
                ('token_expires_at', models.DateTimeField(blank=True, null=True)),
                ('is_enabled', models.BooleanField(default=False)),
                ('connected_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_instagram_integration_settings', to=settings.AUTH_USER_MODEL)),
            ],
            options={'verbose_name': 'اتصال اینستاگرام', 'verbose_name_plural': 'اتصال اینستاگرام'},
        ),
    ]
