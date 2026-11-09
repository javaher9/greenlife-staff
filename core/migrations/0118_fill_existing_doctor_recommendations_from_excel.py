"""Fill only the 48 existing recommendation titles from the doctor's XLSX.

The exact clinician-supplied text and the original CRM media references are
stored in a checksum-verified, compressed source snapshot in core/data.
Existing editor-authored rich content is left untouched; no catalog titles,
patient prescriptions or diet templates are ever created/replaced here.
"""
import base64
import hashlib
import json
from pathlib import Path
import zlib

from django.db import migrations
from django.utils import timezone


PAYLOAD_NAME = 'doctor_recommendations_2026_11.b64'
EXPECTED_ITEMS = 48
EXPECTED_SHA256 = '4a7395f64bbe505670e778d4b7c9136ab322a07898eeb84a462412ce9bc5f896'


def _load_source():
    file_path = Path(__file__).resolve().parent.parent / 'data' / PAYLOAD_NAME
    rows = file_path.read_text(encoding='utf-8').splitlines()
    if len(rows) < 3 or rows[0] != 'GLRECOMMENDATIONS-ZLIB-BASE64-V1':
        raise ValueError('Invalid recommendation source header.')
    if rows[1] != 'sha256:' + EXPECTED_SHA256:
        raise ValueError('Invalid recommendation source manifest.')
    binary = base64.b64decode(''.join(rows[2:]), validate=True)
    if hashlib.sha256(binary).hexdigest() != EXPECTED_SHA256:
        raise ValueError('Recommendation content checksum mismatch; import stopped.')
    entries = json.loads(zlib.decompress(binary).decode('utf-8'))
    if not isinstance(entries, list) or len(entries) != EXPECTED_ITEMS:
        raise ValueError('Unexpected recommendation content count.')
    names = [e.get('title') for e in entries]
    if len(set(names)) != EXPECTED_ITEMS or not all(
        isinstance(name, str) and 0 < len(name) <= 180 for name in names
    ):
        raise ValueError('Unexpected or duplicate source titles.')
    if not all(isinstance(e.get('sections'), list) and e['sections'] for e in entries):
        raise ValueError('Recommendation paragraphs are incomplete.')
    return entries


def fill_missing_recommendations(apps, schema_editor):
    # This migration is deliberately data-only and additive: use the historical
    # app registry so running it does not depend on future model changes.
    Master = apps.get_model('core', 'TreatmentCatalogItem')
    Rich = apps.get_model('core', 'TreatmentRichContent')
    Section = apps.get_model('core', 'TreatmentRichSection')
    Media = apps.get_model('core', 'TreatmentRichMedia')
    entries = _load_source()
    titles = [entry['title'] for entry in entries]
    masters = {
        item.name: item
        for item in Master.objects.filter(
            category='recommendation', branch__isnull=True, name__in=titles,
        )
    }
    missing = [title for title in titles if title not in masters]
    if missing:
        # Never create or approximate an existing title. Continue with exact
        # matches so a legacy/custom database does not suffer a failed deploy.
        print('Recommendation import skipped missing titles: ' + ' | '.join(missing), flush=True)

    added = 0
    preserved = 0
    images = 0
    audios = 0
    for entry in entries:
        master = masters.get(entry['title'])
        if not master:
            continue
        rich, created = Rich.objects.get_or_create(
            master_item_id=master.pk,
            defaults={
                'is_active': master.is_active,
                'origin': 'پیوست اکسل آقای یاوری ۲۰۲۶-۱۱؛ انتقال مستقیم',
                'imported_at': timezone.now(),
            },
        )
        if Section.objects.filter(content_id=rich.pk).exclude(body='').exists():
            preserved += 1
            continue
        changes = []
        if entry.get('subtitle') and not rich.hero_subtitle:
            rich.hero_subtitle = entry['subtitle'][:240]
            changes.append('hero_subtitle')
        if entry.get('cover') and not rich.cover_external_url and not rich.cover_file:
            rich.cover_external_url = entry['cover'][0]
            changes.append('cover_external_url')
        if entry.get('audio') and not rich.audio_external_url and not rich.audio_file:
            rich.audio_external_url = entry['audio'][0]
            changes.append('audio_external_url')
        rich.origin = 'پیوست اکسل آقای یاوری ۲۰۲۶-۱۱؛ انتقال مستقیم'
        rich.imported_at = timezone.now()
        changes.extend(['origin', 'imported_at', 'updated_at'])
        rich.save(update_fields=changes)

        first_section = None
        for order, paragraph in enumerate(entry['sections'], start=1):
            section = Section.objects.create(
                content_id=rich.pk,
                title=paragraph['title'][:200],
                body=paragraph['body'],
                day_number=1,
                meal_slot='other',
                sort_order=order * 10,
            )
            if first_section is None:
                first_section = section
            for idx, url in enumerate(paragraph.get('images', []), start=1):
                Media.objects.create(
                    section_id=section.pk, kind='image', original_url=url,
                    sort_order=idx * 10, inline_before_line=0,
                )
                images += 1
        for order, url in enumerate(entry.get('audio', [])[1:], start=1):
            if first_section:
                Media.objects.create(
                    section_id=first_section.pk, kind='audio', original_url=url,
                    sort_order=order * 10,
                )
                audios += 1
        added += 1
    print(
        f'Existing doctor recommendations: {len(entries)} received, '
        f'{added} filled, {preserved} preserved, {len(missing)} titles missing; '
        f'{images} images and {audios} extra audio links referenced.',
        flush=True,
    )


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0117_align_model_metadata'),
    ]
    operations = [
        migrations.RunPython(fill_missing_recommendations, migrations.RunPython.noop),
    ]
