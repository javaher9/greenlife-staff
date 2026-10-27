from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('payments', '0005_personal_expense_receipt'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SavedPaymentRecipient',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=160)),
                ('iban', models.CharField(blank=True, max_length=34)),
                ('card', models.CharField(blank=True, max_length=24)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('owner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='saved_payment_recipients', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering': ['name', 'pk']},
        ),
        migrations.AddIndex(
            model_name='savedpaymentrecipient',
            index=models.Index(fields=['owner', 'name'], name='payments_sa_owner_i_4b8d0a_idx'),
        ),
    ]
