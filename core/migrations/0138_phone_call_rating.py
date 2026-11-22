import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('core', '0137_copy_aban_targets_to_azar_1405')]

    operations = [
        migrations.CreateModel(
            name='PhoneCallRating',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('call_id', models.UUIDField(editable=False, unique=True)),
                ('score', models.PositiveSmallIntegerField()),
                ('rated_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('operator', models.ForeignKey(
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='phone_call_ratings',
                    to='core.employeeprofile',
                )),
            ],
            options={
                'constraints': [
                    models.CheckConstraint(
                        condition=models.Q(score__gte=1, score__lte=5),
                        name='phone_call_rating_score_1_5',
                    ),
                ],
            },
        ),
    ]
