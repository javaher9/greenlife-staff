"""All 46 approved diet structures from two clinician-supplied XLSX workbooks.

Clinical wording is copied verbatim, never synthesized. Existing rich content
is never overwritten. Pictures of meals are not collected or saved.
"""
from io import BytesIO
import re
from zipfile import BadZipFile, ZipFile
from xml.etree import ElementTree as ET
from django.db import transaction
from django.utils import timezone

from .models import TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection
from .treatment_excel_weekly_import import (
    _col_index, _text, NS, MAX_FILE, WEEKDAY_CODES,
    extract_workbook, import_weekly_diets,
)

RAMADAN_HEADINGS={6:'قبل از سحری',8:'سحری',10:'افطار',
                  12:'بعد از افطار',14:'شام',18:'قبل از خواب'}
RAMADAN_NOTES={16:'نیم ساعت بعد از شام',20:'نصف شب اگر بیدار شدید'}
THIRTEEN_CODES={'Keto-Fast','Z-150','W-150','Cof-150'}

def _rows(raw):
    if len(raw)>MAX_FILE: raise ValueError('حجم فایل اکسل بیش از حد مجاز است.')
    try:
        with ZipFile(BytesIO(raw)) as archive:
            strings=[]
            if 'xl/sharedStrings.xml' in archive.namelist():
                x=ET.fromstring(archive.read('xl/sharedStrings.xml'))
                strings=[''.join(t.text or '' for t in si.findall('.//s:t',NS))
                         for si in x.findall('s:si',NS)]
            root=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            return [{_col_index(c.get('r','')):_text(c,strings)
                     for c in row.findall('s:c',NS)}
                    for row in root.findall('.//s:sheetData/s:row',NS)]
    except (BadZipFile, ET.ParseError, KeyError) as exc:
        raise ValueError('فایل اکسل قابل خواندن نیست.') from exc

def read_all_diets(weight_xlsx,ramadan_xlsx):
    weekly=extract_workbook(weight_xlsx)
    rows=_rows(weight_xlsx)
    if rows[0].get(2)!='کد رژیم':raise ValueError('ساختار فایل رژیم‌های لاغری نادرست است.')
    extra=[]
    codes={e['code'] for e in weekly}
    for line_no,row in enumerate(rows[1:],2):
        code=(row.get(2) or '').strip()
        kind=(row.get(1) or '').strip()
        if not code or code in codes:continue
        if kind not in ('توصیفی','روزانه'):raise ValueError(f'ردیف {line_no}: نوع رژیم ناشناخته.')
        template='thirteen' if code in THIRTEEN_CODES else 'text'
        if kind=='روزانه' and template!='thirteen':
            raise ValueError(f'ردیف {line_no}: رژیم روزانه ساختار تأییدشده ندارد.')
        data={'code':code,'kind':template,'excel_row':line_no,
              'slogan':(row.get(3) or '').strip(),
              'cover':(row.get(66 if kind=='توصیفی' else 4) or '').strip(),
              'audio':(row.get(67 if kind=='توصیفی' else 5) or '').strip()}
        if template=='thirteen' and kind=='روزانه':
            day_blocks=[]
            for day in range(1,14):
                body=(row.get(26+3*(day-1)) or '').strip()
                if not body: raise ValueError(f'رژیم {code} روز {day} خالی است.')
                day_blocks.append((day,body))
            data['days']=day_blocks
            data['day14']=(row.get(65) or '').strip()
        elif template=='thirteen':
            # Cof-150 was exported as descriptive, but its original text
            # contains the 13 numbered days. Preserve every line.
            full_text=(row.get(71) or '').strip()
            # The old Cof export has day 14 as a doctor follow-up, not food.
            # Keep it in explanatory notes rather than appending it to day 13.
            followup=re.search(r'(?m)^\s*روز\s*چهاردهم\b',full_text)
            data['followup']=full_text[followup.start():].strip() if followup else ''
            day_text=full_text[:followup.start()].rstrip() if followup else full_text
            # A legacy row can begin "روز دوم صبح :" without the punctuation
            # understood by the strict 13-day renderer; insert a header separator.
            day_text=re.sub(
                r'(?m)^(\s*روز\s*(?:اول|دوم|سوم|چهارم|پنجم|ششم|هفتم|هشتم|نهم|دهم|یازدهم|دوازدهم|سیزدهم))\s+(?=(?:صبحانه|صبح|ناهار|نهار)\b)',
                r'\1: ',day_text)
            data['raw_days']=day_text
            data['extras']=[str(row.get(i) or '').strip()
                            for i in range(72,110) if str(row.get(i) or '').strip()
                            and not str(row.get(i)).strip().lower().startswith(('http://','https://'))]
            if not data['raw_days']:raise ValueError('متن اصلی ۱۳ روزه Cof-150 خالی است.')
        else:
            data['display_title']=(row.get(68) or '').strip()
            # Exported descriptive files sometimes have genuine prose in
            # nominally "image" columns. Preserve ALL non-URL text in order.
            data['pages']=[str(row.get(i) or '').strip() for i in range(70,110)
                           if str(row.get(i) or '').strip()
                           and not str(row.get(i)).strip().lower().startswith(('http://','https://'))]
            if not data['pages']:raise ValueError(f'محتوای متنی {code} خالی است.')
        extra.append(data)
        codes.add(code)

    ram=_rows(ramadan_xlsx)
    if ram[0].get(1)!='کد رژیم' or ram[0].get(6)!='قبل از سحری':
        raise ValueError('ساختار فایل ماه رمضان نادرست است.')
    for line_no,row in enumerate(ram[1:],2):
        code=(row.get(1) or '').strip()
        if not code:continue
        if code in codes:raise ValueError(f'کد تکراری در دو فایل: {code}')
        parts=[(title,(row.get(col) or '').strip()) for col,title in RAMADAN_HEADINGS.items()
               if (row.get(col) or '').strip()]
        if not parts:raise ValueError(f'رژیم رمضان {code} هیچ وعده‌ای ندارد.')
        extra.append({'code':code,'kind':'ramadan','excel_row':line_no,
            'cover':(row.get(3) or '').strip(),'audio':(row.get(4) or '').strip(),
            'slogan':(row.get(2) or '').strip(),'common':parts,
            'notes':[(title,(row.get(col) or '').strip())
                     for col,title in RAMADAN_NOTES.items() if (row.get(col) or '').strip()],
            'quota':(row.get(21) or '').strip(),'free':(row.get(22) or '').strip(),
            'instructions':(row.get(23) or '').strip()})
        codes.add(code)
    expected={'weekly':34,'thirteen':4,'text':5,'ramadan':3}
    actual={'weekly':len(weekly),'thirteen':sum(e['kind']=='thirteen' for e in extra),
            'text':sum(e['kind']=='text' for e in extra),
            'ramadan':sum(e['kind']=='ramadan' for e in extra)}
    if actual!=expected:
        raise ValueError(f'تعداد رژیم‌ها مطابق توافق نیست: {actual}؛ انتظار {expected}')
    return weekly,extra

def import_remaining_diets(extra,actor):
    result={'created':0,'filled':0,'skipped':0}
    with transaction.atomic():
        for item_data in extra:
            code=item_data['code']
            item=TreatmentCatalogItem.objects.select_for_update().filter(
                category='diet',branch__isnull=True,name=code).first()
            if item and TreatmentRichSection.objects.filter(content__master_item=item).exists():
                result['skipped']+=1
                continue
            if not item:
                item=TreatmentCatalogItem.objects.create(
                    category='diet',name=code,branch=None,is_active=False,created_by=actor)
                result['created']+=1
            content,_=TreatmentRichContent.objects.select_for_update().get_or_create(
                master_item=item,defaults={'is_active':False})
            if content.sections.exists():
                result['skipped']+=1
                continue
            kind=item_data['kind']
            if kind=='thirteen':
                if 'days' in item_data:
                    src='\n'.join('روز %d\n%s' % (n,body)
                                  for n,body in item_data['days'])
                    content.diet_notes_text=item_data.get('day14','')
                else:
                    src=item_data['raw_days']
                    content.diet_notes_text='\n\n'.join(
                        x for x in [item_data.get('followup','')]+item_data.get('extras',[]) if x)
                TreatmentRichSection.objects.create(
                    content=content,title='برنامه غذایی',body=src,meal_slot='other',
                    day_number=1,sort_order=10)
            elif kind=='text':
                for pos,body in enumerate(item_data['pages'],1):
                    TreatmentRichSection.objects.create(
                        content=content,title=item_data.get('display_title') or code,
                        body=body,meal_slot='other',day_number=1,sort_order=pos*10)
            elif kind=='ramadan':
                TreatmentRichSection.objects.create(
                    content=content,title='برنامه غذایی',
                    body='\n'.join('%s\n%s' % (title,body)
                                   for title,body in item_data['common']),
                    meal_slot='other',day_number=1,sort_order=10)
                content.quota_text=item_data['quota']
                content.free_foods_text=item_data['free']
                notes=[item_data['instructions']]+[
                    '%s\n%s' % (title,body) for title,body in item_data['notes']]
                content.diet_notes_text='\n\n'.join(x for x in notes if x)
            content.presentation_template=kind
            content.slogan=item_data['slogan'][:240]
            content.cover_external_url=item_data['cover'][:1300]
            content.audio_external_url=item_data['audio'][:1300]
            if kind=='text':content.display_title=item_data.get('display_title','')[:160]
            content.origin='ورود اکسل مورد تأیید؛ در انتظار بازبینی'
            content.imported_at=timezone.now()
            content.is_active=False
            content.save()
            item.is_active=False
            item.save(update_fields=['is_active','updated_at'])
            result['filled']+=1
    return result

def import_all_diets(weight_xlsx,ramadan_xlsx,actor):
    weekly,extra=read_all_diets(weight_xlsx,ramadan_xlsx)
    with transaction.atomic():
        w=import_weekly_diets(weekly,actor)
        e=import_remaining_diets(extra,actor)
    return {'created':w['created']+e['created'],'filled':w['filled']+e['filled'],
            'skipped':w['skipped']+e['skipped'],'weekly':w,'other':e}
