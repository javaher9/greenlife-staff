from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0060_instagram_integration'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WhatsAppNumber',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('label', models.CharField(max_length=100)),
                ('phone_number', models.CharField(db_index=True, max_length=32)),
                ('display_name', models.CharField(blank=True, max_length=120)),
                ('phone_number_id', models.CharField(blank=True, max_length=120, null=True, unique=True)),
                ('business_account_id', models.CharField(blank=True, db_index=True, max_length=120)),
                ('connection_status', models.CharField(choices=[('pending', 'در انتظار اتصال'), ('connected', 'متصل'), ('disconnected', 'قطع'), ('error', 'خطا')], db_index=True, default='pending', max_length=20)),
                ('is_active', models.BooleanField(default=True)),
                ('quality_rating', models.CharField(blank=True, max_length=40)),
                ('last_webhook_at', models.DateTimeField(blank=True, null=True)),
                ('last_error', models.CharField(blank=True, max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='whatsapp_numbers', to='core.branch')),
            ],
            options={
                'ordering': ['label', 'id'],
            },
        ),
        migrations.CreateModel(
            name='WhatsAppMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('wa_message_id', models.CharField(blank=True, max_length=180, null=True, unique=True)),
                ('contact_phone', models.CharField(db_index=True, max_length=32)),
                ('contact_name', models.CharField(blank=True, max_length=140)),
                ('direction', models.CharField(choices=[('inbound', 'ورودی'), ('outbound', 'خروجی')], db_index=True, max_length=12)),
                ('message_type', models.CharField(default='text', max_length=32)),
                ('body', models.TextField(blank=True)),
                ('status', models.CharField(choices=[('received', 'دریافت شد'), ('queued', 'در صف'), ('sent', 'ارسال شد'), ('delivered', 'تحویل شد'), ('read', 'خوانده شد'), ('failed', 'ناموفق')], db_index=True, default='received', max_length=20)),
                ('is_ai', models.BooleanField(default=False)),
                ('is_read_by_staff', models.BooleanField(db_index=True, default=False)),
                ('metadata', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('delivered_at', models.DateTimeField(blank=True, null=True)),
                ('read_at', models.DateTimeField(blank=True, null=True)),
                ('sent_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='sent_whatsapp_messages', to=settings.AUTH_USER_MODEL)),
                ('whatsapp_number', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='core.whatsappnumber')),
            ],
            options={
                'ordering': ['-created_at', '-id'],
            },
        ),
        migrations.AddIndex(
            model_name='whatsappnumber',
            index=models.Index(fields=['connection_status', 'is_active'], name='wa_num_status_active_idx'),
        ),
        migrations.AddIndex(
            model_name='whatsappmessage',
            index=models.Index(fields=['whatsapp_number', '-created_at'], name='wa_msg_num_created_idx'),
        ),
        migrations.AddIndex(
            model_name='whatsappmessage',
            index=models.Index(fields=['contact_phone', '-created_at'], name='wa_msg_contact_created_idx'),
        ),
    ]
