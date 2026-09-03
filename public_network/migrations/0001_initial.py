# Generated manually for the isolated Green Life public referral network.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import public_network.models


class Migration(migrations.Migration):
    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PublicNetworkMember',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('code', models.CharField(db_index=True, default=public_network.models._new_code, max_length=24, unique=True)),
                ('phone', models.CharField(db_index=True, max_length=30)),
                ('photo', models.ImageField(upload_to='public-network/people/%Y/%m/')),
                ('source', models.CharField(choices=[('story', 'استوری گرین لایف'), ('referral', 'لینک معرف'), ('qr', 'QR معرف'), ('direct', 'ورود مستقیم')], db_index=True, default='direct', max_length=20)),
                ('source_url', models.URLField(blank=True, max_length=500)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('sponsor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='members', to='public_network.publicnetworkmember')),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='public_network_member', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['-created_at']},
        ),
        migrations.AddIndex(
            model_name='publicnetworkmember',
            index=models.Index(fields=['sponsor', 'is_active', '-created_at'], name='pubnet_sponsor_active_idx'),
        ),
        migrations.AddIndex(
            model_name='publicnetworkmember',
            index=models.Index(fields=['source', '-created_at'], name='pubnet_source_date_idx'),
        ),
    ]
