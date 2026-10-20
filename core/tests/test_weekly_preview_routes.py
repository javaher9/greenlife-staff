"""Regression coverage for the exact legacy links and spaced Persian weekdays."""
from types import SimpleNamespace
from django.contrib.auth.models import User
from django.test import TestCase, SimpleTestCase
from django.urls import reverse
from core.models import TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection
from core.diet_week_plan import day_label, build_orange_week


class SpacedWeekdayTests(SimpleTestCase):
    def test_joined_spaced_and_zwnj_days_are_equivalent(self):
        for number, variants in enumerate((('شنبه',), ('یکشنبه', 'یک شنبه', 'یک‌شنبه'),
                ('دوشنبه', 'دو شنبه', 'دو‌شنبه'), ('سهشنبه', 'سه شنبه', 'سه‌شنبه'),
                ('چهارشنبه', 'چهار شنبه', 'چهار‌شنبه'), ('پنجشنبه', 'پنج شنبه', 'پنج‌شنبه'), ('جمعه',)), 1):
            for name in variants:
                with self.subTest(name=name):
                    self.assertEqual(day_label(name+': مقدار اصلی'), ((number,), 'مقدار اصلی'))

    def test_each_dinner_stays_on_its_own_day(self):
        body='صبحانه\nصبحانه مشترک\nشام\n'+ '\n'.join(
            name+': شام اختصاصی '+str(n) for n,name in enumerate(
                ('شنبه','یکشنبه','دو شنبه','سه شنبه','چهار شنبه','پنجشنبه','جمعه'),1))
        section=SimpleNamespace(body=body,title='برنامه غذایی',meal_slot='other',day_number=1,
            media=SimpleNamespace(all=lambda: []))
        week=build_orange_week([section])
        for n in range(1,8):
            self.assertEqual([c['body'] for c in week[n] if c['slot']=='dinner'], ['شام اختصاصی '+str(n)])
            self.assertEqual([c['body'] for c in week[n] if c['slot']=='breakfast'], ['صبحانه مشترک'])

    def test_separate_excel_days_are_not_repeated_or_combined(self):
        sections=[SimpleNamespace(body='صبحانه\nصبحانه '+str(n),title='برنامه غذایی',
            meal_slot='other',day_number=n,media=SimpleNamespace(all=lambda: [])) for n in range(1,8)]
        week=build_orange_week(sections)
        for n in range(1,8):
            self.assertEqual([c['body'] for c in week[n]], ['صبحانه '+str(n)])


class WeeklyPreviewRouteTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('weekly-review','weekly@example.com','test-pass')
        self.client.force_login(self.admin)
        item=TreatmentCatalogItem.objects.create(category='diet',name='Gol-150')
        self.content=TreatmentRichContent.objects.create(master_item=item,presentation_template='weekly')
        self.source='صبحانه\nغذای مشترک\nشام\nشنبه: شام اول\nیکشنبه: شام دوم\nدو شنبه: شام سوم\nچهار شنبه: شام پنجم'
        TreatmentRichSection.objects.create(content=self.content,title='برنامه غذایی',body=self.source,day_number=1)
        self.url=reverse('treatment_content_preview',args=[item.pk])

    def test_old_preview_link_renders_approved_cards_for_every_day(self):
        for n in range(1,8):
            page=self.client.get(self.url+'?day='+str(n))
            self.assertEqual(page.status_code,200)
            self.assertTemplateUsed(page,'core/diet_daily.html')
            self.assertEqual(page.context['day'],n)
            self.assertTrue(page.context['orange_only'])
            self.assertContains(page,'غذای مشترک')
            self.assertNotContains(page,'نسخه آزمایشی پنج محتوای CRM')
        self.assertContains(self.client.get(self.url+'?day=3'),'شام سوم')
        self.assertNotContains(self.client.get(self.url+'?day=2'),'شام سوم')
        self.assertNotContains(self.client.get(self.url+'?day=4'),'شام پنجم')
        self.assertEqual(self.content.sections.get().body,self.source)

    def test_admin_can_still_inspect_original_source(self):
        page=self.client.get(self.url+'?source=1')
        self.assertTemplateUsed(page,'core/treatment_content_preview.html')
        self.assertContains(page,'دو شنبه: شام سوم')

    def test_recommendations_retain_their_original_preview(self):
        item=TreatmentCatalogItem.objects.create(category='recommendation',name='توصیه آزمایشی')
        TreatmentRichContent.objects.create(master_item=item)
        page=self.client.get(reverse('treatment_content_preview',args=[item.pk]))
        self.assertTemplateUsed(page,'core/treatment_content_preview.html')
