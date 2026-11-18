from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0134_lead_call_plaque')]
    operations = [
        migrations.AddField(
            model_name='callcenterleadgroup', name='guidance',
            field=models.TextField(blank=True, default=''),
        ),
    ]
