"""Build an accessible, interleaved meal/photo view without altering source text.

All imported media remain in the database. Responsive-only duplicate images
are omitted from the preview (not deleted) and files with no placement still
appear in the existing gallery below the section.
"""
from itertools import groupby


def build_section_preview(section):
    media=list(section.media.all())
    lines=section.body.splitlines()
    valid=[
        medium for medium in media
        if medium.kind=='image'
        and medium.url
        and not medium.is_responsive_duplicate
        and medium.inline_before_line is not None
        and 0<=medium.inline_before_line<=len(lines)
    ]
    valid.sort(key=lambda medium:(medium.inline_before_line,medium.sort_order,medium.pk))
    grouped=[
        (position,list(group))
        for position,group in groupby(
            valid,key=lambda medium:medium.inline_before_line
        )
    ]
    rows=[]
    cursor=0
    for idx,(position,images) in enumerate(grouped):
        if position>cursor:
            rows.append({'text':'\n'.join(lines[cursor:position]),'images':[]})
        next_position=grouped[idx+1][0] if idx+1<len(grouped) else len(lines)
        rows.append({
            'text':'\n'.join(lines[position:next_position]),
            'images':images,
        })
        cursor=next_position
    if not grouped or cursor<len(lines):
        rows.append({'text':'\n'.join(lines[cursor:]),'images':[]})
    used_ids={medium.pk for medium in valid}
    section.preview_rows=rows
    section.footer_images=[
        medium for medium in media
        if medium.kind=='image' and medium.pk not in used_ids
        and not medium.is_responsive_duplicate and medium.url
    ]
    section.audio_media=[
        medium for medium in media if medium.kind=='audio' and medium.url
    ]
    return section
