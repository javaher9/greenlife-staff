from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0091_four_diet_formats')]

    operations = [
        migrations.CreateModel(
            name='CallCenterRoutingDay',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('date', models.DateField(unique=True)),
                ('opening_at', models.DateTimeField()),
                ('opening_lead_ids', models.JSONField(default=list)),
                ('early_operator_ids', models.JSONField(default=list)),
                ('allocation_counts', models.JSONField(default=dict)),
                ('settled_at', models.DateTimeField(blank=True, null=True)),
            ],
            options={'ordering': ['-date']},
        ),
    ]
