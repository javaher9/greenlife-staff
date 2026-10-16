"""Prepare one non-repeated set of supplementary diet sections for display.

Separate clinical source stays untouched. A duplicate paragraph is skipped only
when its normalized text is identical; distinct medical instructions are kept.
"""
import re
from types import SimpleNamespace


def _canonical_title(title):
    title=re.sub(r'\s+',' ',(title or '').replace('ي','ی').replace('ك','ک').replace('‌',' ')).strip()
    if title.startswith('توضیحات') or title.startswith('نکات برنامه'):
        return 'توضیحات'
    if title in ('سهمیه و مواد آزاد','سهمیه و موادغذایی آزاد','سهمیه و مواد غذایی آزاد'):
        return 'سهمیه و مواد آزاد'
    return title


def _normalized(text):
    return re.sub(r'\s+',' ',(text or '').replace('ي','ی').replace('ك','ک').replace('‌',' ')).strip()


def prepare_diet_extras(sections, *,quota_text='',free_foods_text='',notes_text=''):
    """Group same-label sections, avoiding exact duplicate contents and editor copies."""
    extras={}
    seen={}
    for title,body in (
        ('سهمیه‌های روزانه',quota_text),
        ('مواد غذایی آزاد',free_foods_text),
        ('توضیحات',notes_text),
    ):
        if body and body.strip():
            extras[title]=[body.strip()]
            seen[title]={_normalized(body)}

    for section in sections:
        if section.meal_slot!='other' or section.title.strip()=='برنامه غذایی':
            continue
        title=_canonical_title(section.title)
        if not title: continue
        body=(section.body or '').strip()
        if not body: continue
        key=_normalized(body)
        if not key: continue
        bucket=seen.setdefault(title,set())
        if key in bucket:
            continue
        # Avoid showing an identical free-form text again under a synonym.
        if any(key in entries for entries in seen.values()):
            continue
        bucket.add(key)
        extras.setdefault(title,[]).append(body)
    return [
        SimpleNamespace(title=title,body='\n\n'.join(parts))
        for title,parts in extras.items() if parts
    ]
