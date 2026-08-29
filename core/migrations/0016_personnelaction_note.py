from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0015_device_issue'),
    ]

    operations = [
        migrations.AlterField(
            model_name='personnelaction',
            name='action_type',
            field=models.CharField(
                choices=[
                    ('praise', 'تشویق'),
                    ('notice', 'تذکر'),
                    ('warning', 'اخطار'),
                    ('note', 'یادداشت مدیریتی'),
                ],
                max_length=20,
            ),
        ),
    ]
