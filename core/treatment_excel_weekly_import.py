"""Safe, source-preserving Excel ingestion for seven-day diets.

No food photographs are imported. The workbook is the only source of medical
instructions. Existing edited diets are never silently overwritten.
"""
from io import BytesIO
from zipfile import ZipFile, BadZipFile
from xml.etree import ElementTree as ET

from django.db import transaction
from django.utils import timezone

from .models import TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection

NS={'s':'http://schemas.openxmlformats.org/spreadsheetml/2006/main',
    'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships'}
COMMON_SLOTS={7:('fasting','ناشتا'),9:('breakfast','صبحانه'),
              11:('snack_am','میان‌وعده صبح'),13:('pre_lunch','قبل از ناهار'),
              15:('lunch','ناهار'),17:('snack_pm','عصرانه'),
              19:('pre_dinner','قبل از شام'),21:('dinner','شام'),
              23:('bedtime','قبل از خواب')}
WEEKDAY_CODES={'Saf-150 مزاج گرم و خشک','Dam-160','Dam-150 گرم و تر',
    'Bal-160','Bal-150','Sod-160','Sod-150'}
MAX_FILE=4_000_000

def _col_index(a1):
    n=0
    for char in a1:
        if not char.isalpha(): break
        n=n*26+ord(char.upper())-64
    return n-1

def _text(cell,strings):
    typ=cell.get('t','')
    if typ=='inlineStr':
        return ''.join(t.text or '' for t in cell.findall('.//s:t',NS))
    value=cell.find('s:v',NS)
    if value is None: return ''
    if typ=='s':
        try: return strings[int(value.text or '0')]
        except (ValueError,IndexError): return ''
    return value.text or ''

def extract_workbook(file_bytes):
    if len(file_bytes)>MAX_FILE: raise ValueError('فایل اکسل بیش از ۴ مگابایت است.')
    try:
        with ZipFile(BytesIO(file_bytes)) as archive:
            names=set(archive.namelist())
            if 'xl/worksheets/sheet1.xml' not in names:
                raise ValueError('شیت نخست اکسل پیدا نشد.')
            strings=[]
            if 'xl/sharedStrings.xml' in names:
                root=ET.fromstring(archive.read('xl/sharedStrings.xml'))
                strings=[''.join(x.text or '' for x in si.findall('.//s:t',NS))
                         for si in root.findall('s:si',NS)]
            root=ET.fromstring(archive.read('xl/worksheets/sheet1.xml'))
            rows=[]
            for row in root.findall('.//s:sheetData/s:row',NS):
                values={}
                for c in row.findall('s:c',NS):
                    v=_text(c,strings)
                    if v: values[_col_index(c.get('r',''))]=v
                if values: rows.append(values)
    except (BadZipFile,ET.ParseError,KeyError) as exc:
        raise ValueError('فایل XLSX معتبر نیست یا خواندن شیت ناموفق بود.') from exc
    if not rows or rows[0].get(2)!='کد رژیم' or rows[0].get(1)!='ساختار رژیم':
        raise ValueError('فایل اکسل با ستون‌های مورد انتظار رژیم‌ها مطابقت ندارد.')
    selected=[]
    seen=set()
    for excel_row,row in enumerate(rows[1:],start=2):
        code=(row.get(2) or '').strip()
        kind=(row.get(1) or '').strip()
        eligible=kind=='هفتگی (عمومی)' or (kind=='روزانه' and code in WEEKDAY_CODES)
        if not eligible: continue
        if not code: raise ValueError(f'ردیف {excel_row}: کد رژیم خالی است.')
        if code in seen: raise ValueError(f'ردیف {excel_row}: کد تکراری {code}')
        seen.add(code)
        common=[(slot,title,row.get(index,'').strip()) for index,(slot,title) in COMMON_SLOTS.items()
                if row.get(index,'').strip()]
        days=[(day,(row.get(26+3*(day-1)) or '').strip()) for day in range(1,8)
              if (row.get(26+3*(day-1)) or '').strip()]
        if not common and not days:
            raise ValueError(f'ردیف {excel_row}: رژیم {code} هیچ متن غذایی ندارد.')
        selected.append({'code':code,'legacy_id':row.get(0,''),'common':common,
             'days':days,'cover':row.get(4,'').strip(),'audio':row.get(5,'').strip(),
             'slogan':row.get(3,'').strip(),'excel_row':excel_row})
    if len(selected)!=34:
        raise ValueError(f'فایل ناقص یا متفاوت است: {len(selected)} رژیم هفت‌روزه یافت شد؛ انتظار ۳۴ مورد بود.')
    return selected

def validate_batch(entries):
    report=[]
    for e in entries:
        item=TreatmentCatalogItem.objects.filter(
            category='diet',branch__isnull=True,name=e['code']).first()
        if item:
            has_sections=TreatmentRichSection.objects.filter(content__master_item=item).exists()
            status='دارای محتوای فعلی؛ بدون بازنویسی' if has_sections else 'قابل تکمیل'
        else: status='جدید'
        report.append({'code':e['code'],'status':status,'days':len(e['days']),
            'cover':bool(e['cover']),'row':e['excel_row']})
    return report

def import_weekly_diets(entries,actor):
    report={'created':0,'filled':0,'skipped':0,'codes':[]}
    with transaction.atomic():
        for e in entries:
            code=e['code']
            item=TreatmentCatalogItem.objects.select_for_update().filter(
                category='diet',branch__isnull=True,name=code).first()
            if item:
                if TreatmentRichSection.objects.filter(content__master_item=item).exists():
                    report['skipped']+=1
                    continue
            else:
                item=TreatmentCatalogItem.objects.create(
                    category='diet',name=code,branch=None,is_active=False,created_by=actor)
                report['created']+=1
            content,_=TreatmentRichContent.objects.select_for_update().get_or_create(
                master_item=item,defaults={'is_active':False})
            if content.sections.exists():
                report['skipped']+=1
                continue
            # Explicit day numbers are stored intact, without guessing which foods
            # belong to which meal. Source paragraphs are clinician-owned.
            for i,(slot,title,body) in enumerate(e['common'],start=1):
                TreatmentRichSection.objects.create(content=content,title=title,body=body,
                    day_number=0,meal_slot=slot,sort_order=i*10)
            for day,body in e['days']:
                TreatmentRichSection.objects.create(content=content,title='برنامه غذایی',
                    body=body,day_number=day,meal_slot='other',sort_order=100+day)
            content.presentation_template='weekly'
            content.cover_external_url=e['cover'][:1300]
            content.audio_external_url=e['audio'][:1300]
            content.slogan=e['slogan'][:240]
            content.origin='Excel رژیم‌های لاغری — ورود محافظت‌شده'
            content.imported_at=timezone.now()
            content.is_active=False
            content.save()
            item.is_active=False
            item.save(update_fields=['is_active','updated_at'])
            report['filled']+=1
            report['codes'].append(code)
    return report
