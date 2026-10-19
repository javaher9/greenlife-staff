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


def build_thirteen_days(sections, *, infer_first_keto_day=False):
    """Return exact-day cards and any source text requiring manual review.

    For the separately approved Keto-Fast source ONLY: a leading sequence
    starting explicitly with 'صبحانه' belongs to day 1 when the first
    numbered day is 2 (or no numbered days are present). Do not generalize
    undated prose or synthesize snacks/other days. The CRM text is never edited.
    """
    sections=list(sections)
    source=defaultdict(lambda:defaultdict(list))
    shared=defaultdict(list)
    edited=defaultdict(lambda:defaultdict(list))
    unassigned=[]
    for section in sections:
        if section.meal_slot!='other':
            if section.day_number not in range(14):
                continue
            if not (section.body or '').strip():
                # Do not render empty editor slots as invented meals.
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
        nonempty=[line for line in source_lines if line.strip()]
        first_line=nonempty[0] if nonempty else ''
        first_explicit=next(
            (day for line in source_lines
             if (info:=get_explicit_day(line)) for day in (info[0],)),
            None,
        )
        # A leading Keto-Fast breakfast was historically exported without the
        # "روز ۱" heading. Only that documented boundary gets implicit day 1.
        leading_breakfast_day=(
            infer_first_keto_day
            and meal_label(first_line) is not None
            and meal_label(first_line)[0]=='breakfast'
            and first_explicit in (None,2)
        )

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
            if heading and active_day is None and leading_breakfast_day:
                active_day=1
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
