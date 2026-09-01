from django.db import migrations, models
import django.db.models.deletion


ROLE_CHOICES = [
    ('admin', 'مدیر سیستم'),
    ('internal_manager', 'مدیر داخلی'),
    ('manager', 'مدیر شعبه'),
    ('call_center', 'کال‌سنتر'),
    ('consultant', 'مشاور'),
    ('employee', 'کارمند'),
    ('referrer', 'معرف مشتری'),
]


class Migration(migrations.Migration):
    dependencies = [('core', '0022_call_center_role')]

    operations = [
        migrations.AlterField(
            model_name='employeeprofile',
            name='role',
            field=models.CharField(choices=ROLE_CHOICES, default='employee', max_length=20),
        ),
        migrations.AlterField(
            model_name='checklisttemplate',
            name='role',
            field=models.CharField(blank=True, choices=ROLE_CHOICES, max_length=20),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='entry_type',
            field=models.CharField(choices=[('inc', 'درآمد'), ('exp', 'هزینه')], default='inc', max_length=10),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='person_name',
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='account_heading',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='terminal_or_payee',
            field=models.CharField(blank=True, max_length=160),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='tracking_number',
            field=models.CharField(blank=True, max_length=100),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='destination_card',
            field=models.CharField(blank=True, max_length=80),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='description',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='receipt_image',
            field=models.ImageField(blank=True, null=True, upload_to='finance/receipts/%Y/%m/%d/'),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='review_status',
            field=models.CharField(
                choices=[
                    ('pending', 'در انتظار بررسی'),
                    ('approved', 'تأییدشده'),
                    ('needs_correction', 'نیازمند اصلاح'),
                    ('cancelled', 'ابطال‌شده'),
                ],
                default='approved',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='recorded_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='recorded_financial_transactions', to='auth.user'),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='reviewed_by',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reviewed_financial_transactions', to='auth.user'),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='reviewed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='review_note',
            field=models.CharField(blank=True, max_length=300),
        ),
    ]
