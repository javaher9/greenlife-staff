from django.db import migrations, models


def assign_known_pilot_templates(apps, schema_editor):
    Content = apps.get_model('core', 'TreatmentRichContent')
    db = schema_editor.connection.alias
    Content.objects.using(db).filter(
        master_item__category='diet',master_item__name='Por-150',
    ).update(presentation_template='weekly')
    Content.objects.using(db).filter(
        master_item__category='diet',master_item__name='R-250',
    ).update(presentation_template='ramadan')


class Migration(migrations.Migration):
    dependencies=[('core','0089_orange_fasting_slot')]
    operations=[
        migrations.AddField(
            model_name='treatmentrichcontent',name='presentation_template',
            field=models.CharField(max_length=12,default='legacy',choices=[
                ('legacy','ساختار اصلی'),('weekly','برنامه هفت‌روزه'),('ramadan','برنامه ماه رمضان'),
            ]),
        ),
        migrations.AddField(model_name='treatmentrichcontent',name='quota_text',field=models.TextField(blank=True)),
        migrations.AddField(model_name='treatmentrichcontent',name='free_foods_text',field=models.TextField(blank=True)),
        migrations.AddField(model_name='treatmentrichcontent',name='diet_notes_text',field=models.TextField(blank=True)),
        migrations.AlterField(
            model_name='treatmentrichsection',name='meal_slot',
            field=models.CharField(max_length=16,default='other',choices=[
                ('other','بخش عمومی'),('fasting','ناشتا'),('breakfast','صبحانه'),
                ('snack_am','میان‌وعده صبح'),('pre_lunch','قبل از ناهار'),
                ('lunch','ناهار'),('snack_pm','عصرانه'),('pre_dinner','قبل از شام'),
                ('dinner','شام'),('bedtime','قبل از خواب'),
                ('pre_suhoor','قبل از سحری'),('suhoor','سحری'),
                ('iftar','افطار'),('after_iftar','بعد از افطار'),
            ]),
        ),
        migrations.RunPython(assign_known_pilot_templates,migrations.RunPython.noop),
    ]
