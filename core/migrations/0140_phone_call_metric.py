from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0139_assistant_call_queue')]

    operations = [
        migrations.CreateModel(
            name='PhoneCallMetric',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('call_id', models.UUIDField(editable=False, unique=True)),
                ('direction', models.CharField(choices=[('inbound', 'ورودی'), ('outbound', 'خروجی')], max_length=8)),
                ('outcome', models.CharField(choices=[('answered', 'پاسخ‌داده'), ('unanswered', 'بی‌پاسخ')], max_length=10)),
                ('occurred_at', models.DateTimeField(db_index=True)),
                ('duration_seconds', models.PositiveIntegerField()),
            ],
            options={
                'constraints': [
                    models.CheckConstraint(
                        condition=models.Q(direction__in=('inbound', 'outbound')),
                        name='phone_metric_direction_valid',
                    ),
                    models.CheckConstraint(
                        condition=models.Q(outcome='answered') | models.Q(outcome='unanswered', duration_seconds=0),
                        name='phone_metric_outcome_valid',
                    ),
                ],
            },
        ),
    ]
