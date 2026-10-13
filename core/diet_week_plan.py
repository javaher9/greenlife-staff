"""Read-only seven-day interpretation for the Por-150 ("orange") diet only.

Keep all imported clinical text untouched. Editable sections override the
inferred text for their explicit day and meal. Never infer calories.
"""
import re
from collections import defaultdict

DAYS=('شنبه','یکشنبه','دوشنبه','سه‌شنبه','چهارشنبه','پنجشنبه','جمعه')
SLOTS=('fasting','breakfast','snack_am','lunch','snack_pm','dinner','other')
LABELS={'fasting':'ناشتا','breakfast':'صبحانه','snack_am':'میان‌وعده صبح',
        'lunch':'ناهار','snack_pm':'عصرانه','dinner':'شام','other':'توضیحات'}
ICONS={'fasting':'◉','breakfast':'☀','snack_am':'☘','lunch':'☀','snack_pm':'☕','dinner':'☾','other':'✦'}
DAY_TOKEN=r'(?:چهارشنبه|پنج\s*شنبه|سه\s*شنبه|دوشنبه|یکشنبه|شنبه|جمعه)'
DAY_LINE=re.compile(r'^('+DAY_TOKEN+r'(?:\s*(?:و|،|,|/)\s*'+DAY_TOKEN+r')*)\s*([:：\-–])?\s*(.*)$')
HEAD=re.compile(r'^(میان\s*وعده\s*(?:صبح|عصر)?|صبحانه|ناهار|عصرانه|شام|ناشتا|قبل\s*از\s*صبحانه)\s*([:：\-–])?\s*(.*)$')
ALTERNATIVE=re.compile(r'^\s*(?:یا|گزینه\s*(?:اول|دوم|1|2|۱|۲)\s*[:：]?)\s*$')


def normalize(text):
    return (text or '').replace('\u200c',' ').replace('ي','ی').replace('ك','ک').strip()


def day_label(line):
    match=DAY_LINE.match(normalize(line))
    if not match or (not match.group(2) and match.group(3)):
        return None
    labels=re.findall(DAY_TOKEN,match.group(1))
    indices=[]
    for label in labels:
        key=normalize(label).replace(' ','')
        found=next((i+1 for i,name in enumerate(DAYS) if normalize(name).replace(' ','')==key),None)
        if found and found not in indices: indices.append(found)
    return (tuple(indices),match.group(3).strip()) if indices else None


def meal_label(line):
    match=HEAD.match(normalize(line))
    if not match or (not match.group(2) and match.group(3)):
        return None
    title=''.join(match.group(1).split())
    if title in ('ناشتا','قبلازصبحانه'): slot='fasting'
    elif title=='صبحانه': slot='breakfast'
    elif title=='ناهار': slot='lunch'
    elif title=='شام': slot='dinner'
    elif title in ('عصرانه','میانوعدهعصر'): slot='snack_pm'
    else: slot='snack_am'
    return slot,match.group(3).strip()


def pictures(section):
    return [m for m in section.media.all() if m.kind=='image' and m.url and not m.is_responsive_duplicate]


def make_card(slot,lines,*,title='',photo='',calories=None,source='legacy',alternatives=False):
    body='\n'.join(str(line) for line in lines if str(line).strip()).strip()
    return {'slot':slot,'label':LABELS.get(slot,'توضیحات'),'icon':ICONS.get(slot,'✦'),
            'title':title or LABELS.get(slot,'توضیحات'),
            'summary':body.splitlines()[:3],'body':body,'photo':photo or '',
            'calories':calories,'source':source,'alternatives':alternatives,'audio':''}


def split_options(lines):
    variants=[[]]
    for line in lines:
        if ALTERNATIVE.fullmatch(normalize(line)) and variants[-1]:
            variants.append([])
        else: variants[-1].append(line)
    variants=[v for v in variants if v]
    return variants


def parse_legacy(section):
    """Parse only explicit headings and weekday labels; keep unclear text intact."""
    common=defaultdict(list)
    weekdays=defaultdict(lambda:defaultdict(list))
    lines=section.body.splitlines()
    blocks=[]
    slot='other'
    block=None
    def begin(new_slot,day_ids,i):
        nonlocal block
        block={'slot':new_slot,'days':day_ids,'start':i,'end':i,'lines':[]}
        blocks.append(block)
    for i,raw in enumerate(lines):
        line=re.sub(r'^\s*[-•●*]\s*','',normalize(raw))
        if not line: continue
        heading=meal_label(line)
        if heading:
            slot,rest=heading
            begin(slot,None,i)
            if rest: block['lines'].append(rest)
            continue
        weekday=day_label(line)
        if weekday:
            day_ids,rest=weekday
            begin(slot,day_ids,i)
            if rest:
                sub=meal_label(rest)
                if sub:
                    block['slot'],rest=sub
                if rest: block['lines'].append(rest)
            continue
        if block is None: begin(slot,None,i)
        block['lines'].append(line)
        block['end']=i

    media=pictures(section)
    for b in blocks:
        photo=''
        for pic in media:
            p=pic.inline_before_line
            if p is not None and b['start']<=p<=b['end']+1:
                photo=pic.url
                break
        alternatives=split_options(b['lines'])
        for group in alternatives:
            item=make_card(b['slot'],group,title=LABELS.get(b['slot'],section.title),
                           photo=photo,alternatives=len(alternatives)==2)
            if b['days']:
                for day in b['days']: weekdays[day][b['slot']].append(item)
            else: common[b['slot']].append(item)
    return common,weekdays


def build_orange_week(sections):
    """Seven displayed days; explicit sections take precedence over parsed ones.

    Day 0 sections are shared across the week; 1..7 are day overrides.
    Exactly two *marked alternatives* rotate every other day. Clinical amounts
    and food choices are never inferred from prose containing inline 'یا'.
    """
    sections=list(sections)
    source_shared=defaultdict(list)
    source_days=defaultdict(lambda:defaultdict(list))
    editor_shared=defaultdict(list)
    editor_days=defaultdict(lambda:defaultdict(list))
    for section in sections:
        if section.meal_slot!='other':
            photos=pictures(section)
            item=make_card(section.meal_slot,section.body.splitlines(),title=section.title,
                           photo=photos[0].url if photos else '',
                           calories=section.estimated_kcal,source='editor')
            if section.day_number==0: editor_shared[section.meal_slot].append(item)
            elif 1<=section.day_number<=7: editor_days[section.day_number][section.meal_slot].append(item)
            continue
        if section.title.strip()=='برنامه غذایی':
            shared,days=parse_legacy(section)
            for slot,cards in shared.items(): source_shared[slot].extend(cards)
            for day,mapping in days.items():
                for slot,cards in mapping.items(): source_days[day][slot].extend(cards)
        else:
            item=make_card('other',section.body.splitlines(),title=section.title)
            if section.day_number in (0,1): source_shared['other'].append(item)
            elif 1<=section.day_number<=7: source_days[section.day_number]['other'].append(item)

    week={}
    for day in range(1,8):
        displayed=[]
        for slot in SLOTS:
            selected=(editor_days[day][slot] or source_days[day][slot] or
                      editor_shared[slot] or source_shared[slot])
            if not selected: continue
            is_alternatives=(
                len(selected)==2 and slot in ('breakfast','snack_am','snack_pm')
                and (all(item['alternatives'] for item in selected) or
                     all('گزینه' in item['title'] for item in selected))
            )
            displayed.extend([selected[(day-1)%2]] if is_alternatives else selected)
        week[day]=displayed
    return week
