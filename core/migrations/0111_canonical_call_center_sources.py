"""Keep every call-center lead within the seven owner-approved folders."""
import re
import unicodedata

from django.db import migrations
from django.db.models import Count


NAMES = (
    'وب سایت', 'مزوهای قدیمی دکتر', 'اینستاگرام', 'VIP',
    'ترکیه', 'شبکه فروش پرسنل', 'کمپ',
)


def source_name(value):
    value = unicodedata.normalize('NFKC', value or '').translate(str.maketrans({'ي': 'ی', 'ك': 'ک'}))
    value = re.sub(r'[\u064b-\u065f\u0670\u0640]', '', value)
    value = re.sub(r'[\u200c\u200d\s]+', ' ', value).strip(' \u00ab\u00bb-–—_').casefold()
    compact = re.sub(r'[\s\-–—_]+', '', value)
    if 'دکتر' in value and re.match(r'^(?:مزو|میز)', value) and (
        'قدیمی' in value or value in ('میزهای آقای دکتر', 'میزهای دکتر جواهریان')
    ):
        return 'مزوهای قدیمی دکتر'
    if compact in ('وبسایت', 'ورودیوبسایت', 'website', 'ورودیwebsite'):
        return 'وب سایت'
    if value in ('اینستاگرام', 'اینستاگرام جدید', 'اینستاگرام - لینک',
                 'اینستاگرام - دستی', 'ورودی اینستاگرام'):
        return 'اینستاگرام'
    if compact in ('ترکیه', 'turkey', 'türkiye|turkey', 'türkiye'):
        return 'ترکیه'
    if value == 'vip':
        return 'VIP'
    if value in ('کمپ', 'ورودی کمپین'):
        return 'کمپ'
    if value == 'شبکه فروش پرسنل':
        return 'شبکه فروش پرسنل'
    return None


def fallback_source_name(value):
    """Classify legacy extra folders without discarding their lead ownership."""
    key = unicodedata.normalize('NFKC', value or '').casefold().replace('ي', 'ی').replace('ك', 'ک')
    if 'vip' in key:
        return 'VIP'
    if 'ترکیه' in key or 'turkey' in key or 'türkiye' in key:
        return 'ترکیه'
    if 'اینستا' in key:
        return 'اینستاگرام'
    if 'کمپ' in key or 'campaign' in key:
        return 'کمپ'
    if any(part in key for part in ('شبکه', 'شرکت', 'همکار', 'پرسنل', 'معرف', 'پیگیری', 'میز', 'مزو')):
        return 'شبکه فروش پرسنل'
    return 'وب سایت'


def consolidate(apps, schema_editor):
    Group = apps.get_model('core', 'CallCenterLeadGroup')
    Lead = apps.get_model('core', 'ReferralLead')
    AuditLog = apps.get_model('core', 'AuditLog')
    clusters = {name: [] for name in NAMES}
    for group in Group.objects.annotate(lead_count=Count('leads')).order_by('id'):
        name = source_name(group.name)
        if name:
            clusters[name].append(group)
    removed = moved = renamed = 0
    for name, groups in clusters.items():
        if not groups:
            Group.objects.create(name=name, owner_id=None, is_default=name == 'شبکه فروش پرسنل')
            continue
        target = min(groups, key=lambda group: (
            0 if group.name == name else 1, -group.lead_count, group.pk,
        ))
        if any(group.is_default for group in groups) and not target.is_default:
            target.is_default = True
            target.save(update_fields=['is_default'])
        for source in groups:
            if source.pk == target.pk:
                continue
            count = Lead.objects.filter(group_id=source.pk).update(group_id=target.pk)
            AuditLog.objects.create(
                action='call_center_group_merge', path='migration:0111', method='SYSTEM',
                object_type='CallCenterLeadGroup', object_id=str(target.pk),
                summary='Call-center source aliases consolidated',
                metadata={'source_id': source.pk, 'source_name': source.name,
                          'target_id': target.pk, 'target_name': name, 'leads_moved': count},
            )
            source.delete()
            removed += 1
            moved += count
        if target.name != name or target.owner_id is not None:
            if target.name != name:
                renamed += 1
            target.name = name
            target.owner_id = None
            target.save(update_fields=['name', 'owner'])
    # Other folders were created ad hoc. Keep the original name and affected
    # lead IDs in the audit trail, then remove the extra folder (including
    # empty ones), so the visible group list contains exactly seven entries.
    for source in Group.objects.exclude(name__in=NAMES).order_by('id'):
        name = fallback_source_name(source.name)
        target = Group.objects.get(name=name)
        lead_ids = list(Lead.objects.filter(group_id=source.pk).values_list('pk', flat=True))
        count = Lead.objects.filter(group_id=source.pk).update(group_id=target.pk)
        AuditLog.objects.create(
            action='call_center_group_merge', path='migration:0111', method='SYSTEM',
            object_type='CallCenterLeadGroup', object_id=str(target.pk),
            summary='Legacy extra call-center folder removed',
            metadata={'source_id': source.pk, 'source_name': source.name,
                      'target_id': target.pk, 'target_name': name,
                      'leads_moved': count, 'lead_ids': lead_ids},
        )
        source.delete()
        removed += 1
        moved += count
    print(f'Call-center source consolidation: {removed} groups merged, {moved} leads moved, {renamed} renamed.')


class Migration(migrations.Migration):
    dependencies = [('core', '0110_merge_doctor_desk_and_vip_groups')]
    operations = [migrations.RunPython(consolidate, migrations.RunPython.noop)]
