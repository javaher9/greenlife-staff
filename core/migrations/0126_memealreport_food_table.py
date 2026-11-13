from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0125_referrallead_school_enrollment')]
    operations = [migrations.AddField(model_name='memealreport', name='food_table', field=models.JSONField(blank=True, default=dict))]
