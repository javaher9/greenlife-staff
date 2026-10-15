"""Admin-approved, one-click and non-destructive diet transfer from legacy CRM.

Only a predetermined GET endpoint. No arbitrary URL, redirects, or credentials.
Keep imported medical content and original image links; where images come from
the trusted legacy host, copy bytes so preview doesn't depend on port 655.
"""
from urllib.parse import quote, urlsplit
import requests
from PIL import Image
from io import BytesIO
from django.db import transaction
from django.utils import timezone

from .models import TreatmentCatalogItem,TreatmentRichContent,TreatmentRichSection,TreatmentRichMedia
from .treatment_content_import import extract_live_diet_html
from .treatment_content_service import _save_resource

CRM_BASE='http://crm.greenlifeclinics.com:655'
ALLOWED_HOSTS={'crm.greenlifeclinics.com','80.210.34.152'}
MAX_IMAGES=40


def _read_capped(url, *, limit):
    """Disallow HTTP redirects and bound both response and duration."""
    response=requests.get(
        url,timeout=(4,14),allow_redirects=False,
        headers={'Accept':'text/html,image/*;q=0.8'},
        stream=True,
    )
    try:
        if response.status_code!=200:
            raise ValueError(f'سرور CRM کد HTTP {response.status_code} برگرداند.')
        raw=bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            raw.extend(chunk)
            if len(raw)>limit:
                raise ValueError('اندازه پاسخ CRM از حد مجاز بیشتر است.')
        return bytes(raw),response.headers.get('Content-Type','')
    finally:
        response.close()


def _copy_images(entry):
    urls={entry.get('cover_url','')}
    for section in entry['sections']:
        urls.update(section['images'])
    copied=0
    for url in sorted(urls):
        if not url or copied>=MAX_IMAGES:
            continue
        parts=urlsplit(url)
        if parts.scheme!='http' or parts.hostname not in ALLOWED_HOSTS or parts.port!=655:
            continue
        try:
            data,mime=_read_capped(url,limit=4_000_000)
            if not mime.lower().startswith('image/'):
                continue
            image=Image.open(BytesIO(data))
            image.verify()
        except (ValueError,requests.RequestException, OSError):
            continue
        entry['image_bytes'][url]=data
        copied+=1
    return copied


def fetch_crm_diet(diet_name):
    url=f'{CRM_BASE}/diet1.php?d={quote(diet_name,safe="")}&c=1'
    try:
        raw,mime=_read_capped(url,limit=8_000_000)
    except requests.RequestException as exc:
        raise ValueError('اتصال GET به CRM روی پورت ۶۵۵ برقرار نشد. محتوای موجود تغییر نکرد.') from exc
    if 'html' not in mime.lower() and not raw[:200].lower().lstrip().startswith((b'<!doctype',b'<html')):
        raise ValueError('پاسخ CRM صفحه HTML قابل پردازش نبود.')
    charset='utf-8'
    if 'charset=' in mime.lower():
        charset=mime.split('charset=')[-1].split(';')[0].strip().strip('"')
    entry=extract_live_diet_html(raw,diet_name,encoding=charset)
    downloaded=_copy_images(entry)
    return entry,downloaded,url


def import_one_crm_diet(item):
    """Fetch *before* transaction; never overwrite already present admin edits."""
    if item.category!='diet' or item.branch_id is not None:
        raise ValueError('فقط برنامه‌های بانک مشترک قابل انتقال هستند.')
    if TreatmentRichSection.objects.filter(content__master_item=item).exists():
        raise ValueError('این برنامه از قبل متن یا عکس دارد؛ برای جلوگیری از بازنویسی انتقال خودکار متوقف شد.')
    entry,downloaded,url=fetch_crm_diet(item.name)
    with transaction.atomic():
        content,created=TreatmentRichContent.objects.select_for_update().get_or_create(
            master_item=item,defaults={'is_active':False,'origin':'دریافت خودکار از CRM'},
        )
        if content.sections.exists():
            raise ValueError('محتوای این رژیم هم‌زمان ویرایش شده است؛ انتقال لغو شد.')
        content.is_active=False
        content.origin='دریافت خودکار از CRM؛ در انتظار تأیید'
        content.imported_at=timezone.now()
        if not content.cover_file and not content.cover_external_url:
            content.cover_external_url=entry['cover_url']
        if not content.audio_file and not content.audio_external_url:
            content.audio_external_url=entry['audio_url']
        if entry['cover_url']:
            _save_resource(content.cover_file,entry['cover_url'],entry['image_bytes'])
        content.save()
        media_saved=0
        for number,source in enumerate(entry['sections'],start=1):
            section=TreatmentRichSection.objects.create(
                content=content,title=source['title'],body=source['body'],
                day_number=1,meal_slot='other',sort_order=number*10,
            )
            for kind,urls in (('image',source['images']),('audio',source['audios'])):
                for i,img_url in enumerate(urls):
                    medium=TreatmentRichMedia(
                        section=section,kind=kind,original_url=img_url,sort_order=(i+1)*10,
                    )
                    if kind=='image':
                        placements=source.get('image_positions',[])
                        if len(placements)==len(urls):
                            match=placements[i]
                            if match['url']==img_url:
                                medium.inline_before_line=match['before_line']
                                medium.is_responsive_duplicate=match['is_responsive_duplicate']
                        if _save_resource(medium.uploaded_file,img_url,entry['image_bytes']):
                            media_saved+=1
                    medium.save()
        return {'sections':len(entry['sections']),'media_saved':media_saved,
                'images_downloaded':downloaded,'missing':entry['missing_image_count'],
                'source_url':url}
