"""Transactional import of the approved MHTML ZIP into reusable master content.

This imports only the five approved content titles and never creates masters.
Subsequent uploads without explicit replacement attach missing embedded photos.
"""
import hashlib
import mimetypes
from django.core.files.base import ContentFile
from django.db import transaction
from django.utils import timezone

from .models import (
    TreatmentCatalogItem, TreatmentRichContent, TreatmentRichMedia, TreatmentRichSection,
)
from .treatment_content_import import extract_approved_samples


def _save_resource(field, url, resources):
    raw=resources.get(url)
    if not raw or field:
        return False
    suffix=(url.split('?')[0].rsplit('.',1)[-1] or 'jpg').lower()
    if suffix not in {'jpg','jpeg','png','webp','gif'}:
        suffix='jpg'
    name=hashlib.sha256(raw).hexdigest()[:25]+'.'+suffix
    field.save(name,ContentFile(raw),save=False)
    return True


@transaction.atomic
def import_five_sample_zip(file_bytes, *, replace_existing=False):
    entries=extract_approved_samples(file_bytes)  # all validation before writes
    resolved=[]
    for entry in entries:
        item=TreatmentCatalogItem.objects.filter(
            category=entry['category'],name=entry['title'],branch__isnull=True,
        ).order_by('pk').first()
        if item is None:
            raise ValueError('عنوان در بانک خدمات یافت نشد: '+entry['title'])
        resolved.append((entry,item))

    result={'created':0,'updated':0,'media_added':0,'files_saved':0,'unchanged':0,'warnings':[]}
    for entry,item in resolved:
        content,created=TreatmentRichContent.objects.select_for_update().get_or_create(
            master_item=item,
            defaults={
                'is_active':True,'origin':'MHTML CRM — پنج نمونه',
                'cover_external_url':entry['cover_url'],'audio_external_url':entry['audio_url'],
                'intro_warning':entry.get('intro_warning',''),
                'imported_at':timezone.now(),
            },
        )
        if created or replace_existing:
            if not created:
                content.sections.all().delete()
                content.cover_external_url=entry['cover_url']
                content.audio_external_url=entry['audio_url']
                content.intro_warning=entry.get('intro_warning','')
                content.origin='MHTML CRM — پنج نمونه'
                content.imported_at=timezone.now()
                content.save()
            for n,section in enumerate(entry['sections'],start=1):
                row=TreatmentRichSection.objects.create(
                    content=content,title=section['title'],body=section['body'],sort_order=n*10,
                )
                for kind,urls in (('image',section['images']),('audio',section['audios'])):
                    for position,url in enumerate(urls,start=1):
                        medium=TreatmentRichMedia(section=row,kind=kind,original_url=url,sort_order=position*10)
                        if kind=='image' and _save_resource(medium.uploaded_file,url,entry['image_bytes']):
                            result['files_saved']+=1
                        medium.save()
                        result['media_added']+=1
            result['created' if created else 'updated']+=1
        else:
            result['unchanged']+=1
            # Update only previously uncopied assets; preserve administrator edits.
            for medium in TreatmentRichMedia.objects.filter(
                section__content=content,kind='image',uploaded_file='',
            ):
                if _save_resource(medium.uploaded_file,medium.original_url,entry['image_bytes']):
                    medium.save(update_fields=['uploaded_file'])
                    result['files_saved']+=1
        if _save_resource(content.cover_file,entry['cover_url'],entry['image_bytes']):
            content.save(update_fields=['cover_file','updated_at'])
            result['files_saved']+=1
        if entry['missing_image_count']:
            result['warnings'].append(f"{entry['title']}: {entry['missing_image_count']} جایگاه تصویر بدون نشانی در خروجی اولیه")
        if not entry['audio_url'] and entry['category']=='diet':
            result['warnings'].append(f"{entry['title']}: نشانی فایل صوتی معتبر در خروجی وجود ندارد")
    return result
