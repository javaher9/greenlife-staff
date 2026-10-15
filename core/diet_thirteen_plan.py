"""Strict thirteen-day renderer: never turn undated legacy prose into invented days."""
import re
from collections import defaultdict

from .diet_week_plan import SLOTS, LABELS, meal_label, make_card, pictures

PERSIAN_TO_ASCII=str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩','01234567890123456789')
DAY_HEADER=re.compile(r'^\s*روز\s*(\d{1,2})\s*(?::|：|[.)\-–]|$)\s*(.*)$')
ORDINALS={'اول':1,'دوم':2,'سوم':3,'چهارم':4,'پنجم':5,'ششم':6,
          'هفتم':7,'هشتم':8,'نهم':9,'دهم':10,'یازدهم':11,'دوازدهم':12,'سیزدهم':13}
WORDS=re.compile(r'^\s*روز\s*('+'|'.join(ORDINALS)+r')\s*(?::|：|[.)\-–]|$)\s*(.*)$')


def get_explicit_day(line):
    line=(line or '').translate(PERSIAN_TO_ASCII).strip()
    match=DAY_HEADER.match(line)
    if match:
        day=int(match.group(1))
        return (day,match.group(2)) if 1<=day<=13 else None
    words=WORDS.match(line)
    if words:
        return ORDINALS[words.group(1)],words.group(2)
    return None


def build_thirteen_days(sections):
    """Return 13 exact-day cards and unassigned source sections for manual review.

    A legacy heading "روز 1" is required. If the source has none, keep it
    in a visible unassigned appendix; do not claim it belongs to day 1.
    Explicitly authored 0-day defaults can be reused across all days.
    """
    source=defaultdict(lambda:defaultdict(list))
    shared=defaultdict(list)
    edited=defaultdict(lambda:defaultdict(list))
    unassigned=[]
    for section in sections:
        if section.meal_slot!='other':
            if section.day_number not in range(14):
                continue
            media=pictures(section)
            card=make_card(section.meal_slot,section.body.splitlines(),
                           title=section.title,photo=media[0].url if media else '',
                           calories=section.estimated_kcal,source='editor')
            if section.day_number==0:
                shared[section.meal_slot].append(card)
            else:
                edited[section.day_number][section.meal_slot].append(card)
            continue
        if section.title.strip()!='برنامه غذایی':
            unassigned.append(section)
            continue
        active_day=None
        current_slot=None
        block=[]
        source_lines=section.body.splitlines()
        photos=pictures(section)
        image_positions=[(m.inline_before_line,m.url) for m in photos if m.inline_before_line is not None]

        def flush():
            if active_day is None or current_slot is None or not block:
                return
            lines=[text for text,_ in block]
            first,last=block[0][1],block[-1][1]
            photo=next((url for pos,url in image_positions if first<=pos<=last+1),'')
            card=make_card(current_slot,lines,photo=photo,source='legacy')
            source[active_day][current_slot].append(card)

        not_placed=[]
        for position,line in enumerate(source_lines):
            day_info=get_explicit_day(line)
            if day_info:
                flush()
                active_day,rest=day_info
                current_slot=None
                block=[]
                if rest:
                    first_slot=meal_label(rest)
                    if first_slot:
                        current_slot,text=first_slot
                        if text:
                            block.append((text,position))
                    else:
                        not_placed.append(line)
                continue
            heading=meal_label(line)
            if heading and active_day is not None:
                flush()
                current_slot,rest=heading
                block=[]
                if rest:
                    block.append((rest,position))
            elif current_slot is not None and active_day is not None:
                if line.strip():
                    block.append((line,position))
            elif line.strip():
                not_placed.append(line)
        flush()
        if not_placed:
            unassigned.append({'title':'متن اصلی بدون روز یا وعده مشخص','body':'\n'.join(not_placed)})
    days={}
    for day in range(1,14):
        cards=[]
        for slot in SLOTS:
            if slot=='other':
                continue
            cards.extend(edited[day][slot] or source[day][slot] or shared[slot])
        days[day]=cards
    return days,unassigned
