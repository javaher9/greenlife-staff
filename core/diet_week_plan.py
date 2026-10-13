"""Weekly diet adapter for the stored MHTML clinical content.

The source text and media are never modified. Imported weekday instructions
are only reorganized for display; explicit editor overrides take precedence.
"""
import re
from collections import defaultdict

DAYS=('شنبه','یکشنبه','دوشنبه','سه‌شنبه','چهارشنبه','پنجشنبه','جمعه')
SLOTS=('fasting','breakfast','snack_am','lunch','snack_pm','dinner','other')
LABELS={'fasting':'ناشتا','breakfast':'صبحانه','snack_am':'میان‌وعده صبح',
        'lunch':'ناهار','snack_pm':'عصرانه','dinner':'شام','other':'توضیحات'}
ICONS={'fasting':'◉','breakfast':'☀','snack_am':'☘','lunch':'☀','snack_pm':'☕','dinner':'☾','other':'✦'}
DAY_TOKEN=r'(?:چهارشنبه|پنجشنبه|سه\s*شنبه|دوشنبه|یکشنبه|شنبه|جمعه)'
DAY_LINE=re.compile(r'^('+DAY_TOKEN+r'(?:\s*(?:و|،|,|/)\s*'+DAY_TOKEN+r')*)\s*([:：\-–])?\s*(.*)$')
HEAD=re.compile(r'^(میان\s*وعده\s*(?:صبح|عصر)?|صبحانه|ناهار|عصرانه|شام|ناشتا|قبل\s*از\s*صبحانه)\s*([:：\-–])?\s*(.*)$')


def normalize(text):
    return (text or '').replace('\u200c',' ').replace('ي','ی').replace('ك','ک').strip()


def day_label(line):
    match=DAY_LINE.match(normalize(line))
    if not match or (not match.group(2) and match.group(3)):
        return None
    labels=re.findall(DAY_TOKEN,match.group(1))
    days=tuple(dict.fromkeys(DAYS.index(''.join(label.split()))+1 for label in labels))
    return (days,match.group(3).strip()) if days else None


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


def images(section):
    return [m for m in section.media.all() if m.kind=='image' and m.url and not m.is_responsive_duplicate]


def card(slot, lines, *, title='', photo='', calories=None, source='legacy'):
    body='\n'.join(str(line) for line in lines if str(line).strip()).strip()
    return {'slot':slot,'label':LABELS.get(slot,'توضیحات'),'icon':ICONS.get(slot,'✦'),
            'title':title or LABELS.get(slot,'توضیحات'), 'summary':body.splitlines()[:3],
            'body':body, 'photo':photo or '', 'calories':calories, 'source':source,'audio':''}


def options(lines):
    parts=[[]]
    for line in lines:
        if re.fullmatch(r'(?:یا|گزینه\s*(?:اول|دوم|1|2|۱|۲)\s*[:：]?)',normalize(line)):
            if parts[-1]: parts.append([])
        else:
            parts[-1].append(line)
    return [part for part in parts if part]


def parse_legacy(section):
    shared=defaultdict(list)
    daily=defaultdict(lambda:defaultdict(list))
    lines=section.body.splitlines()
    blocks=[]
    slot='other'
    block=None
    def begin(new_slot,day_ids,i):
        nonlocal block
        block={'slot':new_slot,'days':day_ids,'start':i,'end':i,'lines':[]}
        blocks.append(block)

    for i,raw in enumerate(lines):
        line=re.sub(r'^[-•●*]\s*','',normalize(raw))
        if not line: continue
        m=meal_label(line)
        if m:
            slot,rest=m
            begin(slot,None,i)
            if rest: block['lines'].append(rest)
            continue
        m=day_label(line)
        if m:
            ids,rest=m
            begin(slot,ids,i)
            if rest: block['lines'].append(rest)
            continue
        if block is None: begin(slot,None,i)
        block['lines'].append(line)
        block['end']=i

    for b in blocks:
        photo=''
        for media in images(section):
            p=media.inline_before_line
            if p is not None and b['start']<=p<=b['end']+1:
                photo=media.url
                break
        for part in options(b['lines']):
            item=card(b['slot'],part,photo=photo,title=LABELS.get(b['slot'],section.title))
            if b['days']:
                for day in b['days']: daily[day][b['slot']].append(item)
            else:
                shared[b['slot']].append(item)
    return shared,daily


def build_week(sections):
    """Seven days; 0=common section, 1..7=explicit clinician override.

    Two common alternatives rotate on alternate weekdays for breakfast and
    snacks. Ordinary food phrases such as 'نان یا برنج' stay unchanged.
    """
    sections=list(sections)
    shared=defaultdict(list)
    daily=defaultdict(lambda:defaultdict(list))
    for section in sections:
        if section.meal_slot!='other':
            media=images(section)
            item=card(section.meal_slot,section.body.splitlines(),title=section.title,
                      photo=media[0].url if media else '',
                      calories=section.estimated_kcal,source='editor')
            if section.day_number==0: shared[section.meal_slot].append(item)
            elif 1<=section.day_number<=7: daily[section.day_number][section.meal_slot].append(item)
            continue
        if section.title.strip()=='برنامه غذایی':
            common,weekdays=parse_legacy(section)
            for slot,items in common.items():
                if not shared[slot]: shared[slot].extend(items)
            for day,mapping in weekdays.items():
                for slot,items in mapping.items():
                    if not daily[day][slot]: daily[day][slot].extend(items)
        else:
            item=card('other',section.body.splitlines(),title=section.title)
            if section.day_number in (0,1): shared['other'].append(item)
            elif 1<=section.day_number<=7: daily[section.day_number]['other'].append(item)

    week={}
    for day in range(1,8):
        displayed=[]
        for slot in SLOTS:
            if daily[day][slot]:
                displayed.extend(daily[day][slot])
                continue
            items=shared[slot]
            if slot in ('breakfast','snack_am','snack_pm') and len(items)==2:
                displayed.append(items[(day-1)%2])
            else: displayed.extend(items)
        week[day]=displayed
    return week
