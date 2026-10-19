"""Excel approval examples cannot alter any existing medical catalog rows."""
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.diet_excel_sample_previews import _source,parse_day_meals


class ExcelDietSamplePreviewTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('excel-sample-admin','test@example.com','pass')
        self.client.force_login(self.admin)

    def test_two_source_rows_have_seven_weekdays_and_real_meals(self):
        for legacy_id in (45,44):
            example=_source(legacy_id)
            self.assertEqual(example['id'],legacy_id)
            self.assertEqual(len(example['days']),7)
            self.assertTrue(example['cover'].startswith('https://crm.greenlifeclinics.com/'))
            for day in example['days']:
                cards=parse_day_meals(day)
                self.assertEqual([card['slot'] for card in cards],
                    ['breakfast','snack_am','lunch','snack_pm','dinner','bedtime'])
                self.assertTrue(all(card['body'] for card in cards))
                self.assertTrue(all(card['photo']=='' for card in cards))
                self.assertTrue(all('meal-' in card['illustration_url'] for card in cards))
                self.assertEqual(cards[-1]['label'],'میان‌وعده شب')

    def test_staff_previews_show_original_clinical_text_by_weekday_without_writes(self):
        from core.models import TreatmentCatalogItem,TreatmentRichContent,TreatmentRichSection
        before=(TreatmentCatalogItem.objects.count(),TreatmentRichContent.objects.count(),
                TreatmentRichSection.objects.count())
        for legacy_id in (45,44):
            url=reverse('excel_diet_sample_preview',args=[legacy_id])
            first=self.client.get(url+'?day=1')
            seventh=self.client.get(url+'?day=7')
            self.assertEqual(first.status_code,200)
            self.assertEqual(seventh.status_code,200)
            self.assertContains(first,'شنبه')
            self.assertContains(first,'میان‌وعده شب')
            self.assertContains(first,'meal-snack-am.svg')
            self.assertContains(first,'meal-snack-pm.svg')
            self.assertContains(first,'meal-bedtime.svg')
            self.assertContains(first,'پیش‌نمایش آزمایشی اکسل')
            self.assertNotContains(first,'<img src="https://crm.greenlifeclinics.com/pages/getfile.aspx?type=picture&v=3&mode=filemanager&file=')
            self.assertContains(seventh,'جمعه')
        after=(TreatmentCatalogItem.objects.count(),TreatmentRichContent.objects.count(),
               TreatmentRichSection.objects.count())
        self.assertEqual(before,after)

    def test_preview_thumbnails_are_visible_to_admin_but_not_regular_staff(self):
        library=self.client.get(reverse('treatment_content_library'))
        self.assertEqual(library.status_code,200)
        self.assertContains(library,'Saf-150')
        self.assertContains(library,'Dam-160')
        self.assertContains(library,'تصویر سربرگ')
        browse=self.client.get(reverse('treatment_content_browse'))
        self.assertContains(browse,'دو نمونه آزمایشی اکسل')
        ordinary=User.objects.create_user('other-staff','other@example.com','pass')
        self.client.force_login(ordinary)
        self.assertNotContains(self.client.get(reverse('treatment_content_browse')),
                               'دو نمونه آزمایشی اکسل',status_code=403)
        self.assertEqual(self.client.get(reverse('excel_diet_sample_preview',args=[45])).status_code,403)

    def test_invalid_sample_and_days_fail_closed(self):
        url=reverse('excel_diet_sample_preview',args=[45])
        self.assertEqual(self.client.get(url+'?day=8').status_code,404)
        self.assertEqual(self.client.get(url+'?day=banana').status_code,404)
        self.assertEqual(self.client.get(reverse('excel_diet_sample_preview',args=[43])).status_code,404)
