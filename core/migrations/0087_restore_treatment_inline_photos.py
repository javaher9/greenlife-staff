"""Place existing imported diet photos beside their original meal rows.

Positions were measured from the user's original five MHTML files, using
the same text-node traversal as the original importer. We never touch the
program text, existing media files, prices, prescriptions or patient records.
"""
from django.db import migrations, models


def restore_photo_positions(apps,schema_editor):
    Medium=apps.get_model('core','TreatmentRichMedia')
    Section=apps.get_model('core','TreatmentRichSection')
    # In the source, responsive layout repeats the lunch/dinner picture once.
    # None marks only that redundant mobile-only duplicate, not a missing image.
    placements={
        'Por-150': [0,3,6,9,12,None,29,32,35,None,52],
        'R-250':   [0,3,None,20,23,26,None,43,46,49],
    }
    for name,indices in placements.items():
        section=Section.objects.using(schema_editor.connection.alias).filter(
            content__master_item__category='diet',
            content__master_item__name=name,
            title='برنامه غذایی',
        ).order_by('pk').first()
        if section is None:
            continue
        images=list(Medium.objects.using(schema_editor.connection.alias).filter(
            section_id=section.pk,kind='image',
        ).order_by('sort_order','pk'))
        # An edited/custom image list must not be shifted using unverified data.
        if len(images)!=len(indices):
            continue
        # Text content may have been edited, but placements are only visual.
        for medium,line in zip(images,indices):
            medium.inline_before_line=line
            medium.is_responsive_duplicate=line is None
        Medium.objects.using(schema_editor.connection.alias).bulk_update(
            images,['inline_before_line','is_responsive_duplicate'],
        )


class Migration(migrations.Migration):
    dependencies=[('core','0086_treatment_rich_content')]
    operations=[
        migrations.AddField(
            model_name='treatmentrichmedia',name='inline_before_line',
            field=models.PositiveSmallIntegerField(blank=True,null=True),
        ),
        migrations.AddField(
            model_name='treatmentrichmedia',name='is_responsive_duplicate',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(restore_photo_positions,migrations.RunPython.noop),
    ]
