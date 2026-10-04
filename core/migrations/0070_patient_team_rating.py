# Generated for GreenLife Staff patient team assessment closeout.
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0069_fatemeh_rad_exact_cleanup'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='PatientTeamRating',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('overall_score', models.PositiveSmallIntegerField(choices=[(1, '۱'), (2, '۲'), (3, '۳'), (4, '۴'), (5, '۵')], default=3)),
                ('cooperation_score', models.PositiveSmallIntegerField(choices=[(1, '۱'), (2, '۲'), (3, '۳'), (4, '۴'), (5, '۵')], default=3)),
                ('purchase_capacity_score', models.PositiveSmallIntegerField(choices=[(1, '۱'), (2, '۲'), (3, '۳'), (4, '۴'), (5, '۵')], default=3)),
                ('tags', models.CharField(blank=True, max_length=500)),
                ('note', models.TextField(blank=True, max_length=1200)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='patient_team_ratings', to=settings.AUTH_USER_MODEL)),
                ('patient', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='team_ratings', to='core.patientprofile')),
            ],
            options={'ordering': ['-updated_at', '-id']},
        ),
        migrations.AddConstraint(
            model_name='patientteamrating',
            constraint=models.UniqueConstraint(fields=('patient', 'author'), name='uniq_patient_rating_author'),
        ),
    ]
