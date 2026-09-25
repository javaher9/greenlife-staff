from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0049_doctor_patient_workspace'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='visitappointment',
            name='care_stage',
            field=models.CharField(
                choices=[
                    ('doctor','در انتظار پزشک'),
                    ('consultant','در انتظار مشاور'),
                    ('payment','در انتظار پرداخت'),
                    ('closed','تکمیل چرخه'),
                ],
                db_index=True,
                default='doctor',
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name='visitappointment',
            name='doctor_completed_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.AddField(
            model_name='visitappointment',
            name='doctor_completed_by',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='doctor_completed_appointments',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='patientdietprogram',
            name='appointment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='diet_programs',
                to='core.visitappointment',
            ),
        ),
        migrations.AddField(
            model_name='patientdeviceprogram',
            name='appointment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='device_programs',
                to='core.visitappointment',
            ),
        ),
        migrations.AddField(
            model_name='patientlipolyticprogram',
            name='appointment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='lipolytic_programs',
                to='core.visitappointment',
            ),
        ),
        migrations.AddField(
            model_name='patientcarenote',
            name='appointment',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='care_notes',
                to='core.visitappointment',
            ),
        ),
    ]
