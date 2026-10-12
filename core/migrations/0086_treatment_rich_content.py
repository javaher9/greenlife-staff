from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[('core','0085_device_type_unit_pricing')]
    operations=[
        migrations.CreateModel(name='TreatmentRichContent',fields=[
            ('id',models.BigAutoField(primary_key=True,serialize=False)),
            ('is_active',models.BooleanField(default=True)),
            ('cover_external_url',models.URLField(blank=True,max_length=1300)),
            ('cover_file',models.ImageField(blank=True,upload_to='treatment-content/covers/%Y/%m/')),
            ('intro_warning',models.TextField(blank=True)),
            ('audio_external_url',models.URLField(blank=True,max_length=1300)),
            ('audio_file',models.FileField(blank=True,upload_to='treatment-content/audio/%Y/%m/')),
            ('origin',models.CharField(blank=True,max_length=100)),
            ('imported_at',models.DateTimeField(blank=True,null=True)),
            ('updated_at',models.DateTimeField(auto_now=True)),
            ('master_item',models.OneToOneField(to='core.treatmentcatalogitem',on_delete=django.db.models.deletion.PROTECT,related_name='rich_content')),
        ],options={'ordering':['master_item__name']}),
        migrations.CreateModel(name='TreatmentRichSection',fields=[
            ('id',models.BigAutoField(primary_key=True,serialize=False)),
            ('title',models.CharField(max_length=200)),
            ('body',models.TextField(blank=True)),
            ('sort_order',models.PositiveSmallIntegerField(default=0)),
            ('content',models.ForeignKey(to='core.treatmentrichcontent',on_delete=django.db.models.deletion.CASCADE,related_name='sections')),
        ],options={'ordering':['sort_order','id']}),
        migrations.CreateModel(name='TreatmentRichMedia',fields=[
            ('id',models.BigAutoField(primary_key=True,serialize=False)),
            ('kind',models.CharField(max_length=8,choices=[('image','تصویر'),('audio','صوت')],default='image')),
            ('original_url',models.URLField(blank=True,max_length=1300)),
            ('uploaded_file',models.FileField(blank=True,upload_to='treatment-content/media/%Y/%m/')),
            ('sort_order',models.PositiveSmallIntegerField(default=0)),
            ('section',models.ForeignKey(to='core.treatmentrichsection',on_delete=django.db.models.deletion.CASCADE,related_name='media')),
        ],options={'ordering':['sort_order','id']}),
    ]
