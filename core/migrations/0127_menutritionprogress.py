from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('core', '0126_memealreport_food_table')]
    operations = [migrations.CreateModel(name='MeNutritionProgress', fields=[
        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
        ('choices', models.JSONField(default=dict)),
        ('updated_at', models.DateTimeField(auto_now=True)),
        ('member', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='nutrition_progress', to='core.customerportalmember')),
    ])]
