"""Regression tests: the 48 clinician recommendation titles are NEVER re-created."""
from io import BytesIO
from xml.sax.saxutils import escape
from zipfile import ZipFile

from django.test import TestCase

from core.models import (
    TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection,
)
from core.treatment_excel_recommendations_import import (
    extract_recommendations_xlsx, recommendation_import_preview,
    import_recommendations_xlsx,
)


def recommendations_workbook(titles):
    def cell(col, row, value):
        return (
            f'<c r="{col}{row}" t="inlineStr"><is>'
            f'<t>{escape(value)}</t></is></c>'
        )
    header = {
        'B': 'نام توصیه', 'C': 'تصویر سربرگ', 'D': 'فایل صوتی',
        'E': 'تیتر صفحه توصیه', 'G': 'متن پاراگراف 1',
    }
    rows = [
        '<row r="1">' + ''.join(cell(key, 1, val)
                                for key, val in header.items()) + '</row>'
    ]
    for n, title in enumerate(titles, 2):
        rows.append(
            f'<row r="{n}">'
            + cell('B', n, title)
            + cell('E', n, 'مقدمه، راهکارها')
            + cell('F', n, 'https://crm.greenlifeclinics.com/images/test.jpg')
            + cell('G', n, 'متن اصلی توصیه شماره ' + str(n))
            + cell('I', n, 'نکات تکمیلی ' + str(n))
            + '</row>'
        )
    xml = ('<?xml version="1.0" encoding="UTF-8"?>'
           '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
           '<sheetData>' + ''.join(rows) + '</sheetData></worksheet>')
    output = BytesIO()
    with ZipFile(output, 'w') as archive:
        archive.writestr('xl/worksheets/sheet1.xml', xml.encode('utf-8'))
    return output.getvalue()


class ExistingRecommendationImportTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.titles = [f'توصیه آماده {i}' for i in range(1, 49)]
        for name in cls.titles:
            TreatmentCatalogItem.objects.create(
                name=name, category='recommendation', branch=None
            )
        cls.original_count = TreatmentCatalogItem.objects.count()

    def parsed(self):
        return extract_recommendations_xlsx(recommendations_workbook(self.titles))

    def test_header_and_all_48_are_parsed_exactly(self):
        values = self.parsed()
        self.assertEqual(len(values), 48)
        self.assertEqual(values[0]['title'], self.titles[0])
        self.assertEqual(values[0]['sections'][0]['body'], 'متن اصلی توصیه شماره 2')
        self.assertEqual(values[0]['sections'][1]['body'], 'نکات تکمیلی 2')
        self.assertEqual(len(values[0]['sections'][0]['images']), 1)

    def test_import_only_updates_existing_masters(self):
        values = self.parsed()
        self.assertEqual(len(recommendation_import_preview(values)), 48)
        result = import_recommendations_xlsx(values)
        self.assertEqual(result['filled'], 48)
        self.assertEqual(result['images'], 48)
        self.assertEqual(TreatmentCatalogItem.objects.count(), self.original_count)
        self.assertEqual(TreatmentRichSection.objects.count(), 96)
        self.assertTrue(
            TreatmentCatalogItem.objects.filter(
                category='recommendation',name=self.titles[0],
                rich_content__sections__body='متن اصلی توصیه شماره 2'
            ).exists()
        )
        # A repeated import must not duplicate the content or images.
        second = import_recommendations_xlsx(values)
        self.assertEqual(second['unchanged'], 48)
        self.assertEqual(TreatmentRichSection.objects.count(), 96)

    def test_clinician_edits_are_not_overwritten_without_confirmation(self):
        values = self.parsed()
        item = TreatmentCatalogItem.objects.get(name=self.titles[0])
        rich = TreatmentRichContent.objects.create(master_item=item,is_active=True)
        TreatmentRichSection.objects.create(
            content=rich,title='قبلی',body='ویرایش پزشک',sort_order=10
        )
        result = import_recommendations_xlsx(values)
        self.assertEqual(result['filled'], 47)
        self.assertEqual(result['unchanged'], 1)
        self.assertTrue(
            TreatmentRichSection.objects.filter(
                content=rich,body='ویرایش پزشک'
            ).exists()
        )
        replace = import_recommendations_xlsx(values,replace_existing=True)
        self.assertEqual(replace['replaced'],48)
        self.assertFalse(
            TreatmentRichSection.objects.filter(
                content=rich,body='ویرایش پزشک'
            ).exists()
        )

    def test_missing_title_aborts_before_any_database_writes(self):
        values = self.parsed()
        values[0]['title'] = 'عنوانی که در بانک وجود ندارد'
        with self.assertRaisesRegex(ValueError, 'عنوان'):
            import_recommendations_xlsx(values)
        self.assertFalse(TreatmentRichContent.objects.exists())

    def test_rejects_unrelated_or_partial_spreadsheet(self):
        with self.assertRaisesRegex(ValueError, 'تعداد'):
            extract_recommendations_xlsx(recommendations_workbook(self.titles[:3]))
