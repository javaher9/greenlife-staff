from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0070_patient_team_rating'),
    ]

    operations = [
        migrations.AlterField(
            model_name='visitappointment',
            name='status',
            field=models.CharField(
                choices=[
                    ('booked','رزرو شده'),
                    ('arrived','مراجعه کرده'),
                    ('completed','انجام شد'),
                    ('no_show','عدم مراجعه'),
                    ('cancelled','لغو شده'),
                ],
                db_index=True,
                default='booked',
                max_length=20,
            ),
        ),
        migrations.RemoveConstraint(
            model_name='visitappointment',
            name='uniq_active_visit_appointment_slot',
        ),
        migrations.AddConstraint(
            model_name='visitappointment',
            constraint=models.UniqueConstraint(
                fields=('branch','appointment_date','appointment_time'),
                condition=~models.Q(status__in=('cancelled','no_show')),
                name='uniq_active_visit_appointment_slot',
            ),
        ),
    ]
