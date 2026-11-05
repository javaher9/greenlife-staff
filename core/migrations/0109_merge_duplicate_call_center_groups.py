"""Combine unambiguous duplicate call-center folders without losing their leads."""
import re
import unicodedata

from django.db import migrations
from django.db.models import Count


DOCTOR_DESK = 'میزهای قدیمی دکتر جواهریان'
DOCTOR_DESK_ALIASES = {
    DOCTOR_DESK,
    'میزهای قدیمی آقای دکتر',
    'میزهای آقای دکتر',
    'میزهای دکتر جواهریان',
    'میز قدیمی دکتر جواهریان',
}


def normalized_name(value):
    value = unicodedata.normalize('NFKC', value or '').translate(str.maketrans({'ي': 'ی', 'ك': 'ک'}))
    value = re.sub(r'[\u064b-\u065f\u0670\u0640]', '', value)
    value = re.sub(r'[\u200c\u200d\s]+', ' ', value).strip(' \u00ab\u00bb-–—_')
    return value.casefold()


DOCTOR_DESK_KEYS = {normalized_name(name) for name in DOCTOR_DESK_ALIASES}


def merge_duplicate_groups(apps, schema_editor):
    Group = apps.get_model('core', 'CallCenterLeadGroup')
    Lead = apps.get_model('core', 'ReferralLead')
    AuditLog = apps.get_model('core', 'AuditLog')
    clusters = {}
    for group in Group.objects.annotate(lead_count=Count('leads')).order_by('id'):
        key = normalized_name(group.name)
        if key in DOCTOR_DESK_KEYS:
            key = normalized_name(DOCTOR_DESK)
        if key:
            clusters.setdefault(key, []).append(group)
    for key, groups in clusters.items():
        if len(groups) < 2:
            continue
        # Keep the established system name when present, otherwise the group
        # containing the most leads. Identifiers on the surviving group stay stable.
        target = min(groups, key=lambda item: (
            0 if key == normalized_name(DOCTOR_DESK) and item.name == DOCTOR_DESK else 1,
            -item.lead_count, item.pk,
        ))
        if any(item.is_default for item in groups) and not target.is_default:
            target.is_default = True
            target.save(update_fields=['is_default'])
        for source in groups:
            if source.pk == target.pk:
                continue
            moved = Lead.objects.filter(group_id=source.pk).update(group_id=target.pk)
            AuditLog.objects.create(
                action='call_center_group_merge', path='migration:0109', method='SYSTEM',
                object_type='CallCenterLeadGroup', object_id=str(target.pk),
                summary='Duplicate call-center groups merged',
                metadata={'source_id': source.pk, 'source_name': source.name,
                          'target_id': target.pk, 'target_name': target.name, 'leads_moved': moved},
            )
            source.delete()


class Migration(migrations.Migration):
    dependencies = [('core', '0108_lead_contact_numbers')]
    operations = [migrations.RunPython(merge_duplicate_groups, migrations.RunPython.noop)]
