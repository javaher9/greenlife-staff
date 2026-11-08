import uuid
import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0114_bulk_sms_automations'), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.CreateModel(name='SmsInterestInvitation', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('token', models.UUIDField(default=uuid.uuid4, unique=True, editable=False)),
        ('number', models.CharField(max_length=11)),
        ('created_at', models.DateTimeField(auto_now_add=True)),
        ('choice', models.CharField(max_length=16, blank=True)),
        ('answered_at', models.DateTimeField(null=True, blank=True)),
        ('callback_at', models.DateTimeField(null=True, blank=True)),
        ('is_test', models.BooleanField(default=True)),
        ('created_by', models.ForeignKey(to=settings.AUTH_USER_MODEL, on_delete=django.db.models.deletion.PROTECT)),
    ])]

