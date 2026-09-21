# Generated for Website Leads integration settings

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0044_cash_payment_currency'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='WebsiteLeadIntegrationSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('endpoint_path', models.CharField(default='/api/integrations/leads/', max_length=255)),
                ('api_key_cipher', models.TextField(blank=True)),
                ('is_enabled', models.BooleanField(default=False)),
                ('last_rotated_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('updated_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='updated_website_lead_settings', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'اتصال لید وب‌سایت',
                'verbose_name_plural': 'اتصال لید وب‌سایت',
            },
        ),
    ]
