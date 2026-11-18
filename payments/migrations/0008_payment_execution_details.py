from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('payments', '0007_align_model_metadata'),
    ]

    operations = [
        migrations.AddField(
            model_name='paymentrequest',
            name='payment_method',
            field=models.CharField(
                blank=True,
                choices=[
                    ('smartpay', 'SmartPay'),
                    ('bank_transfer', 'حواله بانکی'),
                    ('card_to_card', 'کارت‌به‌کارت'),
                    ('pos', 'کارت‌خوان'),
                    ('cash', 'نقدی'),
                    ('other', 'سایر'),
                ],
                max_length=24,
            ),
        ),
        migrations.AddField(
            model_name='paymentrequest',
            name='funding_source',
            field=models.CharField(
                blank=True,
                choices=[
                    ('personal', 'حساب شخصی مدیر'),
                    ('company', 'حساب شرکت'),
                    ('other', 'سایر حساب‌ها'),
                ],
                max_length=16,
            ),
        ),
    ]
