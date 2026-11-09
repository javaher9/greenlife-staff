"""Import the 48 clinician-provided recommendation texts into existing masters only.

No master titles, patient selections, diets, or clinician notes are created or
modified. Uploaded workbook is the sole content source; no generated advice.
Works without third-party XLSX packages, matching our other Excel importers.
"""
from io import BytesIO
import re
from urllib.parse import urlsplit
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET

from django.db import transaction
from django.utils import timezone

from .models import (
    TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection,
    TreatmentRichMedia,
)
from .treatment_excel_weekly_import import NS, _col_index, _text


EXPECTED_COLUMNS = {
    1: 'نام توصیه',
    2: 'تصویر سربرگ',
    3: 'فایل صوتی',
    4: 'تیتر صفحه توصیه',
    6: 'متن پاراگراف 1',
}
BODY_COLUMNS = (6, 8, 10, 12)  # G, I, K, M; photo is one column before text
MAX_UPLOAD_BYTES = 4_000_000
MAX_EXPANDED_BYTES = 12_000_000
EXPECTED_RECOMMENDATIONS = 48


def _media_urls(value):
    """Keep only bounded, absolute HTTP(S) media URLs supplied by the Excel."""
    if not value:
        return []
    candidates = re.findall(r'https?://[^\s,\u060c;<>"]+', str(value))
    result = []
    for candidate in candidates:
        url = candidate.strip().rstrip(').')
        parsed = urlsplit(url)
        if parsed.scheme in ('https', 'http') and parsed.netloc and len(url) <= 1300:
            if url not in result:
                result.append(url)
    return result[:12]


def extract_recommendations_xlsx(file_bytes):
    if not isinstance(file_bytes, bytes) or not file_bytes:
        raise ValueError('فایل اکسل توصیه‌ها خالی است.')
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError('حجم اکسل توصیه‌ها از چهار مگابایت بیشتر است.')
    try:
        with ZipFile(BytesIO(file_bytes)) as archive:
            entries = archive.infolist()
            if len(entries) > 100 or sum(f.file_size for f in entries) > MAX_EXPANDED_BYTES:
                raise ValueError('ساختار فایل بیش از حد بزرگ است.')
            names = set(archive.namelist())
            if 'xl/worksheets/sheet1.xml' not in names:
                raise ValueError('شیت نخست توصیه‌ها پیدا نشد.')
            strings = []
            if 'xl/sharedStrings.xml' in names:
                root = ET.fromstring(archive.read('xl/sharedStrings.xml'))
                strings = [
                    ''.join(x.text or '' for x in si.findall('.//s:t', NS))
                    for si in root.findall('s:si', NS)
                ]
            root = ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            excel_rows = []
            for row in root.findall('.//s:sheetData/s:row', NS):
                fields = {
                    _col_index(cell.get('r', '')): _text(cell, strings)
                    for cell in row.findall('s:c', NS)
                }
                if any(str(x or '').strip() for x in fields.values()):
                    excel_rows.append((int(row.get('r') or len(excel_rows) + 1), fields))
    except (BadZipFile, ET.ParseError, KeyError, OSError, OverflowError) as exc:
        raise ValueError('فایل XLSX توصیه‌ها قابل خواندن نیست.') from exc

    if not excel_rows:
        raise ValueError('فایل هیچ ردیفی ندارد.')
    header = excel_rows[0][1]
    for col, label in EXPECTED_COLUMNS.items():
        actual = ' '.join(str(header.get(col, '')).split())
        if actual != label:
            raise ValueError(f'ستون {col + 1} فایل توصیه‌ها اشتباه است: «{label}» پیدا نشد.')

    results = []
    seen = set()
    for line_no, row in excel_rows[1:]:
        title = str(row.get(1, '')).strip()
        if not title:
            raise ValueError(f'ردیف {line_no}: نام توصیه خالی است.')
        if title in seen:
            raise ValueError(f'ردیف {line_no}: عنوان تکراری «{title}».')
        seen.add(title)
        if len(title) > 180:
            raise ValueError(f'ردیف {line_no}: نام توصیه طولانی است.')
        subtitle = str(row.get(4, '')).strip()
        headings = [p.strip() for p in re.split('[,\u060c]', subtitle) if p.strip()]
        body_sections = []
        for block_no, col in enumerate(BODY_COLUMNS):
            body = str(row.get(col, '') or '').strip()
            image_urls = _media_urls(row.get(col - 1, ''))
            if not body and not image_urls:
                continue
            if not body:
                # Don't produce a blank medical page for image-only columns.
                continue
            heading = (
                headings[block_no] if block_no < len(headings)
                else ('متن توصیه' if block_no == 0 else f'ادامه توصیه {block_no + 1}')
            )
            body_sections.append({
                'title': heading[:200],
                'body': body,
                'images': image_urls,
            })
        if not body_sections:
            raise ValueError(f'ردیف {line_no}: «{title}» متن توصیه ندارد.')
        results.append({
            'title': title,
            'subtitle': subtitle,
            'cover': _media_urls(row.get(2, '')),
            'audio': _media_urls(row.get(3, '')),
            'sections': body_sections,
            'excel_row': line_no,
        })
    if len(results) != EXPECTED_RECOMMENDATIONS:
        raise ValueError(
            f'تعداد توصیه‌ها {len(results)} است؛ انتظار {EXPECTED_RECOMMENDATIONS} مورد داریم. '
            'هیچ محتوایی وارد نشد.'
        )
    return results


def recommendation_import_preview(entries):
    """Validate all 48 exact titles before presenting a confirmation button."""
    source_titles = [item['title'] for item in entries]
    existing = TreatmentCatalogItem.objects.filter(
        branch__isnull=True, category='recommendation', name__in=source_titles,
    ).select_related('rich_content')
    by_name = {}
    for item in existing:
        if item.name in by_name:
            raise ValueError('عنوان تکراری در بانک خدمات: ' + item.name)
        by_name[item.name] = item
    missing = [title for title in source_titles if title not in by_name]
    if missing:
        raise ValueError(
            'عنوان‌های زیر در بانک اصلی موجود نیستند و عنوان جدید ساخته نخواهد شد: '
            + '، '.join(missing)
        )

    rich_ids = [item.pk for item in existing]
    populated = set(
        TreatmentRichSection.objects.filter(
            content__master_item_id__in=rich_ids,
        ).exclude(body='').values_list('content__master_item_id', flat=True).distinct()
    )
    return [
        {
            'title': entry['title'],
            'row': entry['excel_row'],
            'sections': len(entry['sections']),
            'has_existing': by_name[entry['title']].pk in populated,
            'cover': bool(entry['cover']),
            'audio': bool(entry['audio']),
        }
        for entry in entries
    ]


@transaction.atomic
def import_recommendations_xlsx(entries, *, replace_existing=False):
    """Fill existing masters; no implicit overwrite of already edited texts.

    Re-import is idempotent. Explicit replacement affects recommendation
    content only and leaves other catalog types and patient selections alone.
    Existing user-added rich sections survive unless replacement is selected.
    """
    verified = recommendation_import_preview(entries)
    masters = {
        item.name: item for item in TreatmentCatalogItem.objects.select_for_update()
        .filter(category='recommendation', branch__isnull=True,
                name__in=[entry['title'] for entry in entries])
    }
    report = {'filled': 0, 'replaced': 0, 'unchanged': 0, 'images': 0, 'audios': 0}
    for entry, validation in zip(entries, verified):
        master = masters[entry['title']]
        content, created = TreatmentRichContent.objects.select_for_update().get_or_create(
            master_item=master,
            defaults={'is_active': master.is_active,
                      'origin': 'اکسل توصیه‌های لاغری؛ متن تأییدشده مدیر'},
        )
        had_content = content.sections.exclude(body='').exists()
        if had_content and not replace_existing:
            report['unchanged'] += 1
            continue
        if had_content and replace_existing:
            content.sections.all().delete()

        # Keep the existing active/disabled status and any administrator-uploaded
        # cover/audio; fill only the missing external URL slots.
        updates = ['origin', 'imported_at', 'updated_at']
        if entry['subtitle'] and not content.hero_subtitle:
            content.hero_subtitle = entry['subtitle'][:240]
            updates.append('hero_subtitle')
        if entry['cover'] and not content.cover_file and not content.cover_external_url:
            content.cover_external_url = entry['cover'][0]
            updates.append('cover_external_url')
        if entry['audio'] and not content.audio_file and not content.audio_external_url:
            content.audio_external_url = entry['audio'][0]
            updates.append('audio_external_url')
        content.origin = 'اکسل توصیه‌های لاغری؛ انتقال محتوای اصلی'
        content.imported_at = timezone.now()
        content.save(update_fields=updates)

        for index, section in enumerate(entry['sections'], start=1):
            saved = TreatmentRichSection.objects.create(
                content=content, title=section['title'], body=section['body'],
                day_number=1, meal_slot='other', sort_order=index * 10,
            )
            for media_index, url in enumerate(section['images'], start=1):
                TreatmentRichMedia.objects.create(
                    section=saved, kind='image', original_url=url,
                    sort_order=media_index * 10, inline_before_line=0,
                )
                report['images'] += 1
        if had_content:
            report['replaced'] += 1
        else:
            report['filled'] += 1
        # Additional audio URLs in the original Excel are preserved if supplied.
        if len(entry['audio']) > 1 and content.sections.exists():
            first_section = content.sections.first()
            for offset, url in enumerate(entry['audio'][1:], start=1):
                TreatmentRichMedia.objects.create(
                    section=first_section, kind='audio', original_url=url,
                    sort_order=offset * 10,
                )
                report['audios'] += 1
    return report
