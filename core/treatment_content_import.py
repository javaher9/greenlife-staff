"""Strict MHTML ZIP parser for five user-supplied legacy samples.

Never fetches arbitrary URLs and never copies old patient/analysis headers.
Only content sections, embedded image bytes and audio references are imported.
"""
import email
import email.policy
import hashlib
import io
import re
import zipfile
from pathlib import PurePosixPath

from bs4 import BeautifulSoup

APPROVED_ITEMS={
    ('diet','Keto-Fast'), ('diet','Sib-150'),
    ('diet','Por-150'), ('diet','R-250'),
    ('recommendation','نکات طلائی در لاغری'),
}
DIET_HEADINGS={'برنامه غذایی','سهمیه و مواد آزاد','توضیحات'}


def _image_url(value):
    value=(value or '').strip()
    return value if value.startswith(('http://','https://')) and not value.endswith('filename=') else ''


def _content_text(container):
    root=BeautifulSoup(str(container),'html.parser')
    for tag in root.select('script,style,svg,iframe,form,button,audio,source,img'):
        tag.decompose()
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',
                  root.get_text('\n',strip=True)).strip()


def _read_one(payload, filename):
    title=PurePosixPath(filename).stem
    category='recommendation' if title=='نکات طلائی در لاغری' else 'diet'
    if (category,title) not in APPROVED_ITEMS:
        raise ValueError('عنوان نمونه خارج از فهرست مجاز است: '+title)
    message=email.message_from_bytes(payload,policy=email.policy.default)
    parts=list(message.walk())
    htmls=[part.get_payload(decode=True) for part in parts if part.get_content_type()=='text/html']
    if len(htmls)!=1 or not htmls[0]:
        raise ValueError('فایل MHTML فاقد یک صفحه HTML معتبر است: '+title)
    soup=BeautifulSoup(htmls[0],'html.parser')
    top_mains=soup.select('body > main')
    if not top_mains:
        raise ValueError('ساختار صفحه اصلی یافت نشد: '+title)

    resources={}
    for part in parts:
        if part.get_content_maintype()!='image':
            continue
        key=(part.get('Content-Location') or '').strip()
        body=part.get_payload(decode=True)
        if key and body and len(body)<5_000_000:
            resources[key]=body

    sections=[]
    for main in top_mains:
        if category=='diet':
            candidates=[]
            for heading in main.select('h2'):
                label=heading.get_text(' ',strip=True)
                if label in DIET_HEADINGS:
                    candidates.append((label,heading.find_parent('div',class_='flex-1')))
        else:
            primary=main.select_one('section h2')
            label=primary.get_text(' ',strip=True) if primary else title
            candidates=[(label,main.select_one('section.mt-10'))]

        for label,card in candidates:
            if card is None:
                continue
            content=card.find('main')
            if content is None:
                groups=[x for x in card.find_all('div',recursive=False) if not x.find('h2')]
                content=groups[-1] if groups else card
            body=_content_text(content)
            image_urls=[u for img in content.find_all('img') if (u:=_image_url(img.get('src')))]
            audios=[]
            if category=='recommendation':
                audios=[a.get('src','') for a in main.select('audio source')
                        if a.get('src','').startswith(('http://','https://')) and len(a.get('src',''))>40]
            if body or image_urls:
                sections.append({
                    'title':label,'body':body,'images':image_urls,'audios':audios,
                })
    if not sections or not all(x['body'] for x in sections):
        raise ValueError('بخش‌های اصلی محتوا قابل استخراج نیستند: '+title)
    if category=='diet' and not any(x['title']=='برنامه غذایی' for x in sections):
        raise ValueError('برنامه غذایی یافت نشد: '+title)
    if category=='recommendation' and len(sections)!=2:
        raise ValueError('دو بخش توصیه در نمونه یافت نشد.')

    first=top_mains[0]
    headline=first.get_text(' ',strip=True)
    warning_match=re.search(
        r'اخطار\s*:\s*(.*?)(?=لطفا با هدفون|مرورگر شما)',
        headline,flags=re.DOTALL,
    )
    warning=re.sub(r'\s+',' ',warning_match.group(1)).strip() if warning_match else ''
    cover=first.find('img')
    cover_url=_image_url(cover.get('src')) if cover else ''
    source=first.select_one('audio source') if category=='diet' else None
    audio_url=(source.get('src','') if source else '')
    if not audio_url.startswith(('http://','https://')) or len(audio_url)<40:
        audio_url=''
    return {
        'title':title,'category':category,'sections':sections,
        'cover_url':cover_url,'audio_url':audio_url,'intro_warning':warning,
        'image_bytes':resources,'source':'MHTML نمونه CRM',
        'missing_image_count':sum(
            bool(img.get('src','').endswith('filename='))
            for img in soup.find_all('img')
        ),
    }


def extract_approved_samples(zip_bytes):
    """Pure parsing; does not touch the database."""
    if len(zip_bytes)>18_000_000:
        raise ValueError('حجم ZIP بیش از حد مجاز است.')
    entries=[]
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        names=[name for name in zf.namelist() if name.lower().endswith('.mhtml')]
        if len(names)!=5:
            raise ValueError('این مرحله فقط ZIP شامل پنج نمونه MHTML را می‌پذیرد.')
        for name in names:
            if PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts:
                raise ValueError('مسیر فایل ZIP نامعتبر است.')
            info=zf.getinfo(name)
            if info.file_size>5_000_000:
                raise ValueError('حجم نمونه MHTML بیش از حد مجاز است.')
            entries.append(_read_one(zf.read(info),name))
    keys={(entry['category'],entry['title']) for entry in entries}
    if keys!=APPROVED_ITEMS:
        raise ValueError('فهرست پنج نمونه با عناوین مورد انتظار مطابقت ندارد.')
    return entries
