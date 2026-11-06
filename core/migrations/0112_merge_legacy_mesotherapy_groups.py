"""Merge the legacy doctor-desk typo into the mesotherapy group."""
import re
import unicodedata

from django.db import migrations


CANONICAL_NAME = 'مزوهای قدیمی دکتر'


def is_mesotherapy_group(value):
    value = unicodedata.normalize('NFKC', value or '').translate(
        str.maketrans({'ي': 'ی', 'ك': 'ک'})
    )
    value = re.sub(r'[\u064b-\u065f\u0670\u0640]', '', value)
    value = re.sub(r'[\u200c\u200d\s]+', ' ', value).strip().casefold()
    return 'دکتر' in value and 'قدیمی' in value and re.match(r'^(?:مزو|میز)', value)


def merge_groups(apps, schema_editor):
    Group = apps.get_model('core', 'CallCenterLeadGroup')
    Lead = apps.get_model('core', 'ReferralLead')
    AuditLog = apps.get_model('core', 'AuditLog')

    matches = [group for group in Group.objects.order_by('id') if is_mesotherapy_group(group.name)]
    target = next((group for group in matches if group.name == CANONICAL_NAME), None)
    if target is None:
        target = Group.objects.create(name=CANONICAL_NAME, owner_id=None, is_default=False)
        matches.append(target)

    for source in matches:
        if source.pk == target.pk:
            continue
        lead_ids = list(Lead.objects.filter(group_id=source.pk).values_list('pk', flat=True))
        moved = Lead.objects.filter(group_id=source.pk).update(group_id=target.pk)
        AuditLog.objects.create(
            action='call_center_group_merge', path='migration:0112', method='SYSTEM',
            object_type='CallCenterLeadGroup', object_id=str(target.pk),
            summary='Legacy mesotherapy group typo merged',
            metadata={
                'source_id': source.pk, 'source_name': source.name,
                'target_id': target.pk, 'target_name': CANONICAL_NAME,
                'leads_moved': moved, 'lead_ids': lead_ids,
            },
        )
        source.delete()

    updates = []
    if target.name != CANONICAL_NAME:
        target.name = CANONICAL_NAME
        updates.append('name')
    if target.owner_id is not None:
        target.owner_id = None
        updates.append('owner')
    if updates:
        target.save(update_fields=updates)


class Migration(migrations.Migration):
    dependencies = [('core', '0111_canonical_call_center_sources')]
    operations = [migrations.RunPython(merge_groups, migrations.RunPython.noop)]

