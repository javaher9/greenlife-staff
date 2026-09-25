from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0050_doctor_consultant_handoff'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='TreatmentCatalogItem',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('category', models.CharField(choices=[('diet','رژیم'),('recommendation','توصیه'),('device','دستگاه'),('lipolytic','لیپولیتیک'),('print_template','قالب نسخه')], db_index=True, max_length=30)),
                ('name', models.CharField(max_length=180)),
                ('price_toman', models.DecimalField(blank=True, decimal_places=0, max_digits=18, null=True)),
                ('unit_label', models.CharField(blank=True, max_length=80)),
                ('notes', models.CharField(blank=True, max_length=500)),
                ('is_active', models.BooleanField(db_index=True, default=True)),
                ('sort_order', models.PositiveSmallIntegerField(default=100)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('branch', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='treatment_catalog_items', to='core.branch')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_treatment_catalog_items', to=settings.AUTH_USER_MODEL)),
            ],
            options={'ordering':['category','sort_order','name','id']},
        ),
        migrations.AddConstraint(
            model_name='treatmentcatalogitem',
            constraint=models.UniqueConstraint(fields=('category','name','branch'), name='uniq_treatment_catalog_category_name_branch'),
        ),
    ]
