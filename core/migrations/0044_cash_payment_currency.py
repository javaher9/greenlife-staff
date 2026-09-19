from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0043_referrallead_contact_result'),
    ]

    operations = [
        migrations.AddField(
            model_name='financialtransaction',
            name='cash_currency',
            field=models.CharField(blank=True, choices=[('IRR','ریال ایران'),('USD','دلار آمریکا'),('EUR','یورو'),('TRY','لیر ترکیه'),('AED','درهم امارات'),('OTHER','سایر ارزها')], max_length=8),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='cash_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='financialtransaction',
            name='cash_exchange_rate',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='نرخ هر واحد ارز به ریال', max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='referralsale',
            name='payment_method',
            field=models.CharField(blank=True, choices=[('Pos S','Pos S'),('Pos H','Pos H'),('CC P','CC P'),('CC D','CC D'),('CC S','CC S'),('Cash','نقدی')], max_length=20),
        ),
        migrations.AddField(
            model_name='referralsale',
            name='cash_currency',
            field=models.CharField(blank=True, choices=[('IRT','تومان ایران'),('IRR','ریال ایران'),('USD','دلار آمریکا'),('EUR','یورو'),('TRY','لیر ترکیه'),('AED','درهم امارات'),('OTHER','سایر ارزها')], max_length=8),
        ),
        migrations.AddField(
            model_name='referralsale',
            name='cash_amount',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=18, null=True),
        ),
        migrations.AddField(
            model_name='referralsale',
            name='cash_exchange_rate',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='نرخ هر واحد ارز به تومان', max_digits=18, null=True),
        ),
    ]
