"""Batch import of user-approved 46 diets: classification and non-destructive safety."""
from io import BytesIO
from zipfile import ZipFile,ZIP_DEFLATED
from xml.sax.saxutils import escape

from django.contrib.auth.models import User
from django.test import TestCase
from core.models import TreatmentCatalogItem,TreatmentRichContent,TreatmentRichSection
from core.treatment_excel_all_import import read_all_diets,import_all_diets

MOODS=('Saf-150 مزاج گرم و خشک','Dam-160','Dam-150 گرم و تر',
       'Bal-160','Bal-150','Sod-160','Sod-150')
THIRTEEN=('Keto-Fast','Z-150','W-150')
TEXT=('Sib-150','Asl-150','Raw-150','شوک بعد تثبیت','رژیم ِیک هفتگی شوک')

def make_xlsx(records):
    def col(n):
        out=''
        while n:
            n,k=divmod(n-1,26)
            out=chr(65+k)+out
        return out
    xml=[]
    for n,record in enumerate(records,1):
        cells=''.join('<c r="%s%d" t="inlineStr"><is><t>%s</t></is></c>'%
            (col(key+1),n,escape(str(value))) for key,value in sorted(record.items()))
        xml.append('<row r="%d">%s</row>'%(n,cells))
    buf=BytesIO()
    with ZipFile(buf,'w',ZIP_DEFLATED) as stream:
        stream.writestr('xl/worksheets/sheet1.xml',
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>%s</sheetData></worksheet>'%''.join(xml))
    return buf.getvalue()

def files():
    weight=[{0:'شناسه اختصاصی',1:'ساختار رژیم',2:'کد رژیم'}]
    for code in list(MOODS)+['Weekly-%02d'%i for i in range(27)]:
        rec={0:1,1:'روزانه' if code in MOODS else 'هفتگی (عمومی)',
             2:code,9:'روزانه صبحانه',4:'https://example.org/header.png'}
        for n in range(7):rec[26+3*n]='صبحانه: میوه روز %d'%(n+1)
        weight.append(rec)
    for code in THIRTEEN:
        rec={0:1,1:'روزانه',2:code,3:'شعار'}
        for n in range(13):rec[26+3*n]='صبحانه: دستور روز %d'%(n+1)
        weight.append(rec)
    weight.append({0:1,1:'توصیفی',2:'Cof-150',66:'https://example.org/coffee.png',
                   68:'رژیم قهوه',
                   71:'\n'.join('روز دوم صبح : نوشیدنی روز دوم' if i==2 else 'روز %d: صبحانه: نوشیدنی روز %d'%(i,i) for i in range(1,14))+'\nروز چهاردهم: مراجعه به پزشک'})
    for code in TEXT:
        weight.append({0:1,1:'توصیفی',2:code,68:'رژیم متنی',
                       71:'دستور پزشکی واقعی این رژیم',
                       80:'توضیح متنی در ستون غیرمنتظره' if code=='Asl-150' else ''})
    ram=[{0:'شناسه اختصاصی',1:'کد رژیم',6:'قبل از سحری'}]
    for code in ('R-50','R-250','R-150'):
        ram.append({1:code,2:'شعار رمضان',3:'https://example.org/ramadan.png',
            6:'آب قبل از سحری',8:'غذا برای سحری',10:'افطار',14:'شام رمضان',
            21:'سهمیه معتبر',22:'مواد آزاد',23:'توضیحات اصلی'})
    return make_xlsx(weight),make_xlsx(ram)


class AllDietExcelImportTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('all-diet-tester','all@example.org','pass')

    def test_verified_classification_and_no_picture_files(self):
        a,b=read_all_diets(*files())
        self.assertEqual(len(a),34)
        self.assertEqual(len(b),12)
        self.assertEqual(sum(x['kind']=='thirteen' for x in b),4)
        self.assertEqual(sum(x['kind']=='text' for x in b),5)
        self.assertEqual(sum(x['kind']=='ramadan' for x in b),3)
        self.assertEqual(next(x['kind'] for x in b if x['code']=='Cof-150'),'thirteen')
        coffee=next(x for x in b if x['code']=='Cof-150')
        self.assertIn('روز دوم: صبح',coffee['raw_days'])
        self.assertNotIn('روز چهاردهم',coffee['raw_days'])
        self.assertIn('روز چهاردهم',coffee['followup'])
        self.assertIn('توضیح متنی در ستون غیرمنتظره',
                      next(x['pages'] for x in b if x['code']=='Asl-150'))

    def test_import_preserves_existing_and_marks_all_new_inactive(self):
        existing=TreatmentCatalogItem.objects.create(category='diet',name='Weekly-00')
        rc=TreatmentRichContent.objects.create(master_item=existing)
        original=TreatmentRichSection.objects.create(content=rc,title='برنامه غذایی',body='تأیید پزشک',
                                                       meal_slot='other')
        weekly,other=read_all_diets(*files())
        imported_codes={row['code'] for row in weekly+other}
        before_count=TreatmentCatalogItem.objects.filter(category='diet').count()
        untouched_ids=set(TreatmentCatalogItem.objects.filter(category='diet').exclude(name__in=imported_codes).values_list('pk',flat=True))
        result=import_all_diets(*files(),self.admin)
        self.assertEqual(result['filled'],45)
        self.assertEqual(result['skipped'],1)
        # Seeded catalog records vary by database/test order. Count only the
        # rows this import actually creates while checking all 46 input codes.
        self.assertEqual(TreatmentCatalogItem.objects.filter(category='diet').count(),
                         before_count+result['created'])
        self.assertEqual(len(imported_codes),46)
        self.assertSetEqual(set(TreatmentCatalogItem.objects.filter(category='diet',name__in=imported_codes).values_list('name',flat=True)),imported_codes)
        self.assertSetEqual(set(TreatmentCatalogItem.objects.filter(category='diet').exclude(name__in=imported_codes).values_list('pk',flat=True)),untouched_ids)
        original.refresh_from_db()
        self.assertEqual(original.body,'تأیید پزشک')
        for code,kind in [('Cof-150','thirteen'),('R-250','ramadan'),('Sib-150','text')]:
            item=TreatmentCatalogItem.objects.get(category='diet',name=code)
            self.assertEqual(item.rich_content.presentation_template,kind)
            self.assertFalse(item.is_active)
            self.assertFalse(item.rich_content.is_active)
            self.assertTrue(item.rich_content.sections.exists())
            self.assertFalse(item.rich_content.sections.filter(media__kind='image').exists())
        again=import_all_diets(*files(),self.admin)
        self.assertEqual(again['filled'],0)
        self.assertEqual(again['skipped'],46)

    def test_import_requires_both_authorized_files(self):
        a,b=files()
        with self.assertRaises(ValueError): read_all_diets(a,a)
        with self.assertRaises(ValueError): read_all_diets(b,a)
