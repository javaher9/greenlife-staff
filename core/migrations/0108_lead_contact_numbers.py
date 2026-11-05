from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[('core','0107_gandom_manual_flower_placeholder')]
    operations=[
        migrations.AddField(model_name='referrallead',name='initial_description',
                            field=models.TextField(blank=True,null=True,editable=False)),
        migrations.CreateModel(name='LeadContactPhone',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('phone',models.CharField(db_index=True,max_length=30)),
            ('lead',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='extra_phones',to='core.referrallead')),
        ],options={'ordering':['id'],'constraints':[models.UniqueConstraint(fields=('lead','phone'),name='unique_lead_contact_phone')]}),
    ]
