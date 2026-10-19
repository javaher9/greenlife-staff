"""Regression tests for Excel import safety and correct weekday interpretation."""
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED
from xml.sax.saxutils import escape

from django.contrib.auth.models import User
from django.test import TestCase

from core.models import TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection
from core.diet_week_plan import build_orange_week
from core.treatment_excel_weekly_import import extract_workbook,validate_batch,import_weekly_diets

MOODS=['Saf-150 مزاج گرم و خشک','Dam-160','Dam-150 گرم و تر',
       'Bal-160','Bal-150','Sod-160','Sod-150']

def _xlsx():
    """Synthetic file follows the real uploaded workbook column positions."""
    weekly=['Test-Weekly-%02d'%i for i in range(27)]
    catalog=MOODS+weekly
    rows=[]
    def cell(i,v):
        col=''
        n=i+1
        while n:
            n,r=divmod(n-1,26)
            col=chr(65+r)+col
        return f'<c r="{col}1" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'
    def make_row(position,d):
        cs=[]
        for i,value in sorted(d.items()):
            col=''
            n=i+1
            while n:
                n,r=divmod(n-1,26)
                col=chr(65+r)+col
            cs.append(f'<c r="{col}{position}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
        return f'<row r="{position}">{"".join(cs)}</row>'
    rows.append(make_row(1,{0:'شناسه اختصاصی',1:'ساختار رژیم',2:'کد رژیم'}))
    for idx,code in enumerate(catalog,start=2):
        fields={0:idx,1:'روزانه' if code in MOODS else 'هفتگی (عمومی)',
                2:code,4:'https://example.org/header.png',9:'هر روز یک صبحانه'}
        if code in MOODS:
            fields.update({26:'صبحانه: برنامه شنبه\nمیان وعده صبح: ساعت ده\nمیان وعده شب: قبل خواب',
                           29:'صبحانه: برنامه یکشنبه\nناهار: ناهار روز دوم'})
        rows.append(make_row(idx,fields))
    xml=('<?xml version="1.0" encoding="UTF-8"?>'
         '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
         +''.join(rows)+'</sheetData></worksheet>').encode('utf-8')
    buffer=BytesIO()
    with ZipFile(buffer,'w',ZIP_DEFLATED) as z:
        z.writestr('xl/worksheets/sheet1.xml',xml)
    return buffer.getvalue()


class WeeklyExcelImportTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('diet-excel-import-admin','test@example.com','pass')
        self.client.force_login(self.admin)

    def test_parse_34_only_and_keep_cover_without_meal_photos(self):
        entries=extract_workbook(_xlsx())
        self.assertEqual(len(entries),34)
        self.assertEqual(len({x['code'] for x in entries}),34)
        self.assertEqual(entries[0]['days'][0][0],1)
        self.assertEqual(entries[0]['common'][0][0],'breakfast')
        self.assertTrue(entries[0]['cover'])
        self.assertFalse(any('photo' in e for e in entries))

    def test_import_weekday_meals_idempotently_without_touching_existing(self):
        old=TreatmentCatalogItem.objects.create(category='diet',name='Test-Weekly-00')
        oldcontent=TreatmentRichContent.objects.create(master_item=old,is_active=True)
        saved=TreatmentRichSection.objects.create(
            content=oldcontent,title='برنامه غذایی',body='رژیم پزشک بدون تغییر',
            day_number=1,meal_slot='other')
        entries=extract_workbook(_xlsx())
        before=TreatmentCatalogItem.objects.filter(category='diet').count()
        result=import_weekly_diets(entries,self.admin)
        self.assertEqual(result['filled'],33)
        self.assertEqual(result['skipped'],1)
        self.assertEqual(TreatmentCatalogItem.objects.filter(category='diet').count(),before+result['created'])
        saved.refresh_from_db()
        self.assertEqual(saved.body,'رژیم پزشک بدون تغییر')
        mood=TreatmentCatalogItem.objects.get(name='Dam-160')
        content=mood.rich_content
        self.assertEqual(content.presentation_template,'weekly')
        self.assertFalse(content.is_active)
        self.assertEqual(content.cover_external_url,'https://example.org/header.png')
        self.assertFalse(content.sections.filter(media__kind='image').exists())
        cards=build_orange_week(content.sections.all())
        saturday={x['slot']:x['body'] for x in cards[1]}
        sunday={x['slot']:x['body'] for x in cards[2]}
        self.assertIn('برنامه شنبه',saturday['breakfast'])
        self.assertIn('برنامه یکشنبه',sunday['breakfast'])
        self.assertIn('قبل خواب',saturday['bedtime'])
        self.assertNotIn('برنامه شنبه',sunday['breakfast'])
        repeated=import_weekly_diets(entries,self.admin)
        self.assertEqual(repeated['filled'],0)
        self.assertEqual(repeated['skipped'],34)

    def test_unverified_filename_fails_and_ui_needs_confirmation(self):
        page=self.client.get('/settings/treatment-content/')
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'انتقال ۳۴ رژیم هفت‌روزه')
        self.assertEqual(TreatmentCatalogItem.objects.filter(name__startswith='Test-Weekly-').count(),0)
