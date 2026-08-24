from django.db import migrations, models

class Migration(migrations.Migration):
    dependencies = [
        ('core', '0010_camp_module'),
    ]

    operations = [
        migrations.AddField(
            model_name='dailyreport',
            name='client_submission_id',
            field=models.CharField(blank=True, db_index=True, max_length=64, null=True, unique=True),
        ),
    ]
