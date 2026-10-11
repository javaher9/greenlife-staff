from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0081_eybpoosh_marketing_sms'),
    ]

    operations = [
        migrations.CreateModel(
            name='BulkSmsOptOut',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.CharField(max_length=11, unique=True, db_index=True)),
                ('source', models.CharField(default='manual', max_length=32)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name='BulkSmsCampaign',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('body', models.TextField(max_length=600)),
                ('segments', models.JSONField(default=list)),
                ('combine', models.CharField(default='any', max_length=8)),
                ('date_filter', models.JSONField(blank=True, default=dict)),
                ('status', models.CharField(choices=[('draft', 'پیش‌نویس'),('queued','در صف'),('paused','متوقف موقت'),('completed','پایان‌یافته'),('cancelled','لغوشده')], db_index=True, default='draft', max_length=12)),
                ('recipient_count', models.PositiveIntegerField(default=0)),
                ('excluded_count', models.PositiveIntegerField(default=0)),
                ('consent_attested', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('approved_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='bulk_sms_campaigns', to='auth.user')),
            ],
            options={'ordering': ['-created_at','-id']},
        ),
        migrations.CreateModel(
            name='BulkSmsRecipient',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('number', models.CharField(max_length=11)),
                ('status', models.CharField(choices=[('pending','در انتظار'),('sending','در حال ارسال'),('accepted','پذیرفته‌شده'),('failed','ناموفق'),('skipped','حذف‌شده از ارسال')], db_index=True, default='pending', max_length=12)),
                ('reason', models.CharField(blank=True, max_length=140)),
                ('attempted_at', models.DateTimeField(blank=True, null=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('campaign', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='recipients', to='core.bulksmscampaign')),
            ],
        ),
        migrations.AddConstraint(
            model_name='bulksmsrecipient',
            constraint=models.UniqueConstraint(fields=('campaign','number'),name='unique_bulk_sms_campaign_number'),
        ),
        migrations.AddIndex(
            model_name='bulksmsrecipient',
            index=models.Index(fields=['status','attempted_at'],name='bulk_sms_dispatch_idx'),
        ),
    ]
