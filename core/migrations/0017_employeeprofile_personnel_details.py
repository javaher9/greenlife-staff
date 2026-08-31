from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0016_personnelaction_note')]

    operations = [
        migrations.AddField(
            model_name='employeeprofile',
            name='address',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='employeeprofile',
            name='education',
            field=models.CharField(blank=True, max_length=200),
        ),
        migrations.AddField(
            model_name='employeeprofile',
            name='is_insured',
            field=models.BooleanField(blank=True, null=True),
        ),
    ]
