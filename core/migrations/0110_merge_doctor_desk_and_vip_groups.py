"""Merge the doctor-desk spelling mistakes confirmed by the owner."""
import re
import unicodedata

from django.db import migrations
from django.db.models import Count


DOCTOR_DESK = 'میزهای قدیمی دکتر جواهریان'


def key_for(value):
    value = unicodedata.normalize('NFKC', value or '').translate(str.maketrans({'ي': 'ی', 'ك': 'ک'}))
    value = re.sub(r'[\u064b-\u065f\u0670\u0640]', '', value)
    value = re.sub(r'[\u200c\u200d\s]+', ' ', value).strip(' \u00ab\u00bb-–—_').casefold()
    if 'قدیمی' in value and 'دکتر' in value and re.match(r'^(?:مزو|میز)', value):
        return DOCTOR_DESK
    return value


def merge_groups(apps, schema_editor):
    Group = apps.get_model('core', 'CallCenterLeadGroup')
    Lead = apps.get_model('core', 'ReferralLead')
    AuditLog = apps.get_model('core', 'AuditLog')
    clusters = {DOCTOR_DESK: [], 'vip': []}
    merged_groups = 0
    moved_leads = 0
    for group in Group.objects.annotate(lead_count=Count('leads')).order_by('id'):
        key = key_for(group.name)
        if key in clusters:
            clusters[key].append(group)
    for key, groups in clusters.items():
        if len(groups) < 2:
            continue
        preferred = DOCTOR_DESK if key == DOCTOR_DESK else 'VIP'
        target = min(groups, key=lambda group: (
            0 if group.name == preferred else 1, -group.lead_count, group.pk,
        ))
        if any(group.is_default for group in groups) and not target.is_default:
            target.is_default = True
            target.save(update_fields=['is_default'])
        for source in groups:
            if source.pk == target.pk:
                continue
            moved = Lead.objects.filter(group_id=source.pk).update(group_id=target.pk)
            AuditLog.objects.create(
                action='call_center_group_merge', path='migration:0110', method='SYSTEM',
                object_type='CallCenterLeadGroup', object_id=str(target.pk),
                summary='Doctor desk or VIP call-center groups merged',
                metadata={'source_id': source.pk, 'source_name': source.name,
                          'target_id': target.pk, 'target_name': target.name, 'leads_moved': moved},
            )
            source.delete()
            merged_groups += 1
            moved_leads += moved
    print(f'Call-center duplicate merge: {merged_groups} groups, {moved_leads} leads moved.')


class Migration(migrations.Migration):
    dependencies = [('core', '0109_merge_duplicate_call_center_groups')]
    operations = [migrations.RunPython(merge_groups, migrations.RunPython.noop)]
