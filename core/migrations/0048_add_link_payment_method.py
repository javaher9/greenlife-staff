from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0047_referrallead_assigned_at_index'),
    ]

    operations = [
        migrations.AlterField(
            model_name='referralsale',
            name='payment_method',
            field=models.CharField(
                blank=True,
                choices=[
                    ('Pos S','Pos S'),('Pos H','Pos H'),('CC P','CC P'),
                    ('CC D','CC D'),('CC S','CC S'),('LINK','LINK'),('Cash','نقدی'),
                ],
                max_length=20,
            ),
        ),
    ]
