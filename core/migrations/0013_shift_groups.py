from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):
    dependencies = [
        ('core', '0012_attendance_geofence'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShiftGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('is_active', models.BooleanField(default=True)),
                ('note', models.CharField(blank=True, max_length=250)),
                ('branch', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='shift_groups', to='core.branch')),
                ('default_shift', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='default_for_groups', to='core.workshift')),
            ],
        ),
        migrations.AddField(
            model_name='employeeprofile',
            name='shift_group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='employees', to='core.shiftgroup'),
        ),
    ]
