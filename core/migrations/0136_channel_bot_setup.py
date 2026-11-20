from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0135_call_center_group_guidance'),
        ('core', '0135_channel_message_receipt'),
    ]

    operations = [
        migrations.CreateModel(name='ChannelBotSetup', fields=[
            ('provider', models.CharField(choices=[('telegram', 'تلگرام'), ('bale', 'بله')], max_length=12, primary_key=True, serialize=False)),
            ('token_cipher', models.TextField(blank=True)),
            ('secret_cipher', models.TextField(blank=True)),
            ('username', models.CharField(blank=True, max_length=80)),
            ('verified_at', models.DateTimeField(blank=True, null=True)),
        ]),
    ]
