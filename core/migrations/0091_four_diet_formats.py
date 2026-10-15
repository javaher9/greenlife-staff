from django.db import migrations, models


def assign_remaining_pilots(apps, schema_editor):
    Content=apps.get_model('core','TreatmentRichContent')
    db=schema_editor.connection.alias
    for name,kind in [('Keto-Fast','thirteen'),('Sib-150','text')]:
        Content.objects.using(db).filter(
            master_item__category='diet',master_item__name=name,
            presentation_template='legacy',
        ).update(presentation_template=kind)


class Migration(migrations.Migration):
    dependencies=[('core','0090_two_diet_templates')]
    operations=[
        migrations.AlterField(
            model_name='treatmentrichcontent',name='presentation_template',
            field=models.CharField(max_length=12,default='legacy',choices=[
                ('legacy','ساختار اصلی'),('weekly','برنامه هفت‌روزه'),
                ('ramadan','برنامه ماه رمضان'),('thirteen','برنامه سیزده‌روزه'),
                ('text','برنامه متنی'),
            ]),
        ),
        migrations.RunPython(assign_remaining_pilots,migrations.RunPython.noop),
    ]
