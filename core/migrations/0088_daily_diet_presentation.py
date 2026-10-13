from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies=[('core','0087_restore_treatment_inline_photos')]

    operations=[
        migrations.AddField(model_name='treatmentrichcontent',name='display_title',field=models.CharField(blank=True,max_length=160)),
        migrations.AddField(model_name='treatmentrichcontent',name='hero_subtitle',field=models.CharField(blank=True,max_length=240)),
        migrations.AddField(model_name='treatmentrichcontent',name='slogan',field=models.CharField(blank=True,max_length=240)),
        migrations.AddField(model_name='treatmentrichcontent',name='slogan_image',field=models.ImageField(blank=True,upload_to='treatment-content/slogans/%Y/%m/')),
        migrations.AddField(model_name='treatmentrichcontent',name='slogan_external_url',field=models.URLField(blank=True,max_length=1300)),
        migrations.AddField(model_name='treatmentrichsection',name='day_number',field=models.PositiveSmallIntegerField(default=1)),
        migrations.AddField(model_name='treatmentrichsection',name='meal_slot',field=models.CharField(choices=[('other','بخش عمومی'),('breakfast','صبحانه'),('snack_am','میان‌وعده صبح'),('lunch','ناهار'),('snack_pm','عصرانه'),('dinner','شام')],default='other',max_length=16)),
        migrations.AddField(model_name='treatmentrichsection',name='estimated_kcal',field=models.PositiveSmallIntegerField(blank=True,null=True)),
        migrations.CreateModel(name='TreatmentDietDayAudio',fields=[
            ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
            ('day_number',models.PositiveSmallIntegerField()),
            ('audio_file',models.FileField(blank=True,upload_to='treatment-content/daily-audio/%Y/%m/')),
            ('external_url',models.URLField(blank=True,max_length=1300)),
            ('content',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='daily_audio',to='core.treatmentrichcontent')),
        ],options={'ordering':['day_number']}),
        migrations.AddConstraint(model_name='treatmentdietdayaudio',constraint=models.UniqueConstraint(fields=('content','day_number'),name='treatment_diet_day_audio_unique')),
    ]
