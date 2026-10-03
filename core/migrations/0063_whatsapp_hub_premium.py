from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0062_khorshidi_lead_policy_notice'),
    ]

    operations = [
        migrations.AddField(
            model_name='whatsappnumber',
            name='number_type',
            field=models.CharField(
                choices=[
                    ('call_center', 'کال‌سنتر'),
                    ('branch', 'مرکز / شعبه'),
                    ('turkey', 'ترکیه'),
                    ('management', 'مدیریت'),
                    ('other', 'سایر'),
                ],
                db_index=True,
                default='branch',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='whatsappnumber',
            name='responsible',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='whatsapp_numbers',
                to='core.employeeprofile',
            ),
        ),
        migrations.AddField(
            model_name='whatsappmessage',
            name='outbound_mode',
            field=models.CharField(
                blank=True,
                choices=[
                    ('manual', 'دستی'),
                    ('automation', 'اتوماتیک'),
                    ('ai', 'AI'),
                    ('system', 'سیستمی'),
                ],
                db_index=True,
                max_length=12,
            ),
        ),
    ]
