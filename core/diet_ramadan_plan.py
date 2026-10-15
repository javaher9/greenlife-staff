"""Read-only, Ramadan-specific seven-day interpretation of original R-250 diet.

Never rewrite original imported sections or make up meal quantities.
"""
import re
from collections import defaultdict
from .diet_week_plan import DAYS, normalize, parse_legacy, pictures, make_card

SLOTS=('pre_suhoor','suhoor','iftar','after_iftar','dinner','bedtime','other')
LABELS={
    'pre_suhoor':'قبل از سحری','suhoor':'سحری','iftar':'افطار',
    'after_iftar':'بعد از افطار','dinner':'شام','bedtime':'قبل از خواب',
    'other':'توضیحات',
}
HEAD=re.compile(
    r'^(یک\s*ساعت\s*بعد\s*از\s*افطار|بعد\s*از\s*افطار|قبل\s*از\s*سحری|'
    r'قبل\s*از\s*خواب|سحری|افطار|شام)\s*([:：\-–])?\s*(.*)$'
)


def ramadan_meal_label(line):
    match=HEAD.match(normalize(line))
    if not match or (not match.group(2) and match.group(3)):
        return None
    title=''.join(match.group(1).split())
    mapping={
        'قبلازسحری':'pre_suhoor','سحری':'suhoor','افطار':'iftar',
        'یکساعتبعدازافطار':'after_iftar','بعدازافطار':'after_iftar',
        'شام':'dinner','قبلازخواب':'bedtime',
    }
    original=HEAD.match((line or '').strip())
    return mapping[title],(original or match).group(3).strip()


def _uniques(cards):
    seen=set()
    unique=[]
    for card in cards:
        key=(card['slot'],card['body'].strip(),card.get('photo',''))
        if key not in seen:
            unique.append(card)
            seen.add(key)
    return unique


def build_ramadan_week(sections):
    """Weekdays from source; explicit day/meal sections override original."""
    common=defaultdict(list)
    weekdays=defaultdict(lambda:defaultdict(list))
    edited_shared=defaultdict(list)
    edited_days=defaultdict(lambda:defaultdict(list))
    for section in sections:
        if section.meal_slot!='other':
            # A given clinical override replaces only its own slot.
            meal=section.meal_slot
            if meal not in SLOTS:
                continue
            photos=pictures(section)
            card=make_card(
                meal,section.body.splitlines(),title=section.title,
                photo=photos[0].url if photos else '',
                calories=section.estimated_kcal,source='editor',
            )
            card['label']=LABELS.get(meal,section.title)
            if section.day_number==0:
                edited_shared[meal].append(card)
            elif 1<=section.day_number<=7:
                edited_days[section.day_number][meal].append(card)
        elif section.title.strip()=='برنامه غذایی':
            source_common,source_days=parse_legacy(section,heading_detector=ramadan_meal_label)
            for slot,cards in source_common.items():
                for card in cards:
                    card['label']=LABELS.get(slot,card['label'])
                common[slot].extend(cards)
            for day,slotmap in source_days.items():
                for slot,cards in slotmap.items():
                    for card in cards:
                        card['label']=LABELS.get(slot,card['label'])
                    weekdays[day][slot].extend(cards)
    results={}
    for day in range(1,8):
        cards=[]
        for slot in SLOTS:
            selected=(edited_days[day][slot] or weekdays[day][slot] or
                      edited_shared[slot] or common[slot])
            cards.extend(_uniques(selected))
        results[day]=cards
    return results
