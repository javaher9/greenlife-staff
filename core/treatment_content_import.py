"""Strict offline MHTML importer for the five approved CRM samples.

No external dependencies or network calls. Excludes patient-specific CRM headers.
"""
import email
import email.policy
import io
import re
import zipfile
from html.parser import HTMLParser
from pathlib import PurePosixPath

APPROVED_ITEMS={
    ('diet','Keto-Fast'),('diet','Sib-150'),('diet','Por-150'),('diet','R-250'),
    ('recommendation','نکات طلائی در لاغری'),
}
DIET_HEADINGS={'برنامه غذایی','سهمیه و مواد آزاد','توضیحات'}
VOID_TAGS={
    'area','base','br','col','embed','hr','img','input','link','meta',
    'param','source','track','wbr',
}
SKIP_TEXT={'script','style','svg','iframe','form','button','audio','source','img'}


class _Node:
    __slots__=('tag','attrs','children','parent')

    def __init__(self,tag,attrs=(),parent=None):
        self.tag=tag
        self.attrs=dict(attrs)
        self.children=[]
        self.parent=parent

    def get(self,key,default=''):
        return self.attrs.get(key,default) or default

    def classes(self):
        return self.get('class').split()

    def elements(self,tag=None):
        for child in self.children:
            if isinstance(child,_Node):
                if tag is None or tag==child.tag:
                    yield child
                yield from child.elements(tag)

    def first(self,tag):
        return next(self.elements(tag),None)


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root=_Node('document')
        self.stack=[self.root]

    def handle_starttag(self,tag,attrs):
        node=_Node(tag,attrs,self.stack[-1])
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,0,-1):
            if self.stack[i].tag==tag:
                del self.stack[i:]
                break

    def handle_data(self,data):
        self.stack[-1].children.append(data)


def _text(node):
    parts=[]
    def walk(n):
        if isinstance(n,str):
            val=n.strip()
            if val:
                parts.append(val)
        elif n.tag not in SKIP_TEXT:
            for child in n.children:
                walk(child)
    walk(node)
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n','\n'.join(parts)).strip()


def _image_url(value):
    value=(value or '').strip()
    return value if value.startswith(('http://','https://')) and not value.endswith('filename=') else ''


def _parent_class(node,tag,class_name):
    p=node.parent
    while p is not None:
        if p.tag==tag and class_name in p.classes():
            return p
        p=p.parent
    return None


def _content_block(card):
    content=card.first('main')
    if content is not None:
        return content
    groups=[
        child for child in card.children
        if isinstance(child,_Node) and child.tag=='div' and child.first('h2') is None
    ]
    return groups[-1] if groups else card


def _images_with_positions(block):
    """Collect image locations in the exact leaf-text order used by _text().

    A position means 'before this numbered text line'. Mobile-only duplicates
    of the same responsive photo remain in the media bank but aren't repeated.
    """
    lines=[]
    found=[]
    previous=set()

    def walk(node):
        if isinstance(node,str):
            part=node.strip()
            if part:
                lines.append(part)
            return
        if node.tag=='img':
            url=_image_url(node.get('src'))
            if url:
                prefix=re.sub(
                    r'\n[ \t]*\n(?:[ \t]*\n)+','\n\n',
                    '\n'.join(lines),
                ).strip()
                ancestor=node.parent
                mobile=False
                while ancestor is not None:
                    if 'md:hidden' in ancestor.classes():
                        mobile=True
                        break
                    ancestor=ancestor.parent
                duplicate=mobile and url in previous
                found.append({
                    'url':url,
                    'before_line':len(prefix.splitlines()) if prefix else 0,
                    'is_responsive_duplicate':duplicate,
                })
                previous.add(url)
            return
        if node.tag not in SKIP_TEXT:
            for child in node.children:
                walk(child)

    walk(block)
    return found


def _audio_urls(node):
    urls=[]
    for audio in node.elements('audio'):
        for source in audio.elements('source'):
            value=source.get('src')
            if value.startswith(('http://','https://')) and len(value)>40:
                urls.append(value)
    return urls


def _read_one(payload,filename):
    title=PurePosixPath(filename).stem
    category='recommendation' if title=='نکات طلائی در لاغری' else 'diet'
    if (category,title) not in APPROVED_ITEMS:
        raise ValueError('عنوان نمونه خارج از فهرست مجاز است: '+title)
    message=email.message_from_bytes(payload,policy=email.policy.default)
    htmls=[
        part.get_payload(decode=True) for part in message.walk()
        if part.get_content_type()=='text/html'
    ]
    if len(htmls)!=1 or not htmls[0]:
        raise ValueError('فایل MHTML فاقد یک صفحه HTML معتبر است: '+title)
    parser=_Parser()
    parser.feed(htmls[0].decode('utf-8',errors='replace'))
    parser.close()
    body=parser.root.first('body')
    top_mains=[
        child for child in body.children
        if isinstance(child,_Node) and child.tag=='main'
    ] if body else []
    if not top_mains:
        raise ValueError('ساختار صفحه اصلی یافت نشد: '+title)
    resources={}
    for part in message.walk():
        if part.get_content_maintype()!='image':
            continue
        key=(part.get('Content-Location') or '').strip()
        image_bytes=part.get_payload(decode=True)
        if key and image_bytes and len(image_bytes)<5_000_000:
            resources[key]=image_bytes
    sections=[]
    for main in top_mains:
        if category=='diet':
            candidates=[
                (label,_parent_class(heading,'div','flex-1'))
                for heading in main.elements('h2')
                if (label:=_text(heading)) in DIET_HEADINGS
            ]
        else:
            first_heading=next(
                (h for section in main.elements('section') for h in section.elements('h2')),
                None,
            )
            label=_text(first_heading) if first_heading else title
            advice_block=next(
                (node for node in main.elements('section') if 'mt-10' in node.classes()),
                None,
            )
            candidates=[(label,advice_block)]
        for label,card in candidates:
            if card is None:
                continue
            block=_content_block(card)
            content=_text(block)
            image_positions=_images_with_positions(block)
            images=[image['url'] for image in image_positions]
            audios=_audio_urls(main) if category=='recommendation' else []
            if content or images:
                sections.append({
                    'title':label,'body':content,'images':images,
                    'image_positions':image_positions,'audios':audios,
                })
    if not sections or not all(section['body'] for section in sections):
        raise ValueError('بخش‌های اصلی محتوا قابل استخراج نیستند: '+title)
    if category=='diet' and not any(
        section['title']=='برنامه غذایی' for section in sections
    ):
        raise ValueError('برنامه غذایی یافت نشد: '+title)
    if category=='recommendation' and len(sections)!=2:
        raise ValueError('دو بخش توصیه در نمونه یافت نشد.')
    first=top_mains[0]
    cover=first.first('img')
    cover_url=_image_url(cover.get('src')) if cover else ''
    audio=_audio_urls(first) if category=='diet' else []
    audio_url=audio[0] if audio else ''
    missing=sum(
        node.get('src','').endswith('filename=')
        for node in parser.root.elements('img')
    )
    return {
        'title':title,'category':category,'sections':sections,
        'cover_url':cover_url,'audio_url':audio_url,
        'image_bytes':resources,'source':'MHTML نمونه CRM',
        'missing_image_count':missing,
    }


def extract_approved_samples(zip_bytes):
    """Pure offline parsing: exactly the four diets and one recommendation."""
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
    if {(entry['category'],entry['title']) for entry in entries}!=APPROVED_ITEMS:
        raise ValueError('فهرست پنج نمونه با عناوین مورد انتظار مطابقت ندارد.')
    return entries
