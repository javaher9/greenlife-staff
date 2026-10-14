"""Editable meal/photo rows for treatment administrators.

A row edits one original text line and its media anchor.  Imported medical
text is never regenerated or reparsed when changing just one row/image.
"""
import hashlib


def line_signature(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def inline_edit_rows(section):
    lines=section.body.splitlines()
    groups={}
    remaining=[]
    for medium in section.media.all():
        if medium.kind!='image' or medium.is_responsive_duplicate:
            continue
        anchor=medium.inline_before_line
        if anchor is not None and 0<=anchor<=len(lines):
            groups.setdefault(anchor,[]).append(medium)
        else:
            remaining.append(medium)
    rows=[]
    for index in range(len(lines)+1):
        pictures=groups.get(index,[])
        if index==len(lines) and not pictures:
            continue
        text=lines[index] if index<len(lines) else ''
        if not text.strip() and not pictures:
            continue
        rows.append({
            'index':index,
            'text':text,
            'signature':line_signature(text),
            'images':pictures,
            'is_blank':not text.strip(),
        })
    return rows,remaining


def replace_one_line(section,number,signature,new_text):
    """Safely edit exactly one line, retaining original newline separators."""
    if '\r' in new_text or '\n' in new_text:
        raise ValueError('متن هر ردیف باید یک خط باشد؛ برای چند خط از ویرایش کل بخش استفاده کنید.')
    if len(new_text)>5000:
        raise ValueError('متن این ردیف بیش از حد طولانی است.')
    parts=section.body.splitlines(keepends=True)
    if number<0 or number>=len(parts):
        raise ValueError('ردیف انتخاب‌شده موجود نیست.')
    current=parts[number].rstrip('\r\n')
    if signature!=line_signature(current):
        raise ValueError('متن این ردیف تغییر کرده است. صفحه را تازه‌سازی کنید.')
    suffix=parts[number][len(current):]
    parts[number]=new_text+suffix
    section.body=''.join(parts)
    section.save(update_fields=['body'])
