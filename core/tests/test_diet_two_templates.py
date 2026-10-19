"""Separate weekly vs Ramadan diet views, source preservation, and admin settings."""
from importlib import import_module
from django.apps import apps
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from core.models import TreatmentCatalogItem,TreatmentRichContent,TreatmentRichSection
from core.diet_week_plan import parse_legacy
from core.diet_ramadan_plan import build_ramadan_week


class TwoDietLayoutsTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('template-admin','template@example.com','password')
        self.client.force_login(self.admin)
        self.orange=TreatmentCatalogItem.objects.create(category='diet',name='Por-150')
        self.ramadan=TreatmentCatalogItem.objects.create(category='diet',name='R-250')
        self.keto=TreatmentCatalogItem.objects.create(category='diet',name='Keto-Fast')
        self.week=TreatmentRichContent.objects.create(
            master_item=self.orange,presentation_template='weekly',
        )
        self.ram=TreatmentRichContent.objects.create(
            master_item=self.ramadan,presentation_template='ramadan',
        )
        self.other=TreatmentRichContent.objects.create(master_item=self.keto)
        self.week_source=TreatmentRichSection.objects.create(
            content=self.week,title='برنامه غذایی',
            body='ناشتا\nیک لیوان آب\nصبحانه\nنان و پنیر\nساعت ۱۰ صبح\nدو عدد هویج\n'
                 'قبل از ناهار\nدو لیوان آب\nناهار\nشنبه: مرغ و سالاد\nیکشنبه: ماهی و سالاد\n'
                 'عصرانه\nچای\nقبل از شام\nآب گرم\nشام\nشنبه: سوپ\nیکشنبه: عدسی\n'
                 'قبل از خواب\nدمنوش',
        )
        self.ram_source=TreatmentRichSection.objects.create(
            content=self.ram,title='برنامه غذایی',
            body='قبل از سحری\nآب گرم\nسحری\nشنبه: دو عدد خرما\nیکشنبه: تخم مرغ\n'
                 'سحری\nشنبه: دو عدد خرما\nیکشنبه: تخم مرغ\n'
                 'افطار\nنان و خرما\nیک ساعت بعد از افطار\nسیب\n'
                 'شام\nشنبه: خوراک سبزیجات\nیکشنبه: مرغ\n'
                 'شام\nشنبه: خوراک سبزیجات\nیکشنبه: مرغ',
        )
        self.quota=TreatmentRichSection.objects.create(
            content=self.ram,title='سهمیه و مواد آزاد',
            body='یک لیوان شیر یا ماست\nآب و کاهو آزاد',
        )
        self.explain=TreatmentRichSection.objects.create(
            content=self.ram,title='توضیحات',
            body='متن اصلی برنامه و نکات پزشک',
        )

    def test_weekly_source_has_all_distinct_meal_slots_and_seven_days(self):
        common,days=parse_legacy(self.week_source)
        self.assertIn('fasting',common)
        self.assertIn('breakfast',common)
        self.assertIn('snack_am',common)
        self.assertIn('pre_lunch',common)
        self.assertIn('pre_dinner',common)
        self.assertIn('bedtime',common)
        self.assertIn('lunch',days[1])
        # The approved Por-150 pilot intentionally uses the compact daily view.
        # Exercise the separate generic 7-day view with the same source data.
        generic=TreatmentCatalogItem.objects.create(category='diet',name='Test-Weekly-Layout')
        generic_content=TreatmentRichContent.objects.create(
            master_item=generic,presentation_template='weekly',
        )
        TreatmentRichSection.objects.create(
            content=generic_content,title=self.week_source.title,body=self.week_source.body,
        )
        url=reverse('diet_template_preview',args=[generic.pk])
        saturday=self.client.get(url+'?day=1')
        sunday=self.client.get(url+'?day=2')
        self.assertEqual(saturday.status_code,200)
        self.assertEqual(sunday.status_code,200)
        self.assertContains(saturday,'صبحانه')
        self.assertContains(saturday,'دو عدد هویج')
        self.assertContains(saturday,'قبل از ناهار')
        self.assertContains(saturday,'مرغ و سالاد')
        self.assertNotContains(saturday,'ماهی و سالاد')
        self.assertContains(sunday,'ماهی و سالاد')
        self.assertContains(saturday,'<option value="1"')
        self.assertContains(saturday,'<option value="7"')
        self.assertContains(saturday,'touchstart')
        self.assertContains(saturday,'@media(max-width:390px)')
        self.assertContains(saturday,'@media print')
        self.assertNotContains(saturday,'دو عدد خرما')

    def test_ramadan_week_has_suhoor_iftar_late_iftar_and_no_duplicate_source(self):
        days=build_ramadan_week([self.ram_source,self.quota,self.explain])
        slots={card['slot'] for card in days[1]}
        self.assertIn('pre_suhoor',slots)
        self.assertIn('suhoor',slots)
        self.assertIn('iftar',slots)
        self.assertIn('after_iftar',slots)
        self.assertIn('dinner',slots)
        self.assertEqual(len([c for c in days[1] if c['slot']=='suhoor']),1)
        self.assertEqual(len([c for c in days[1] if c['slot']=='dinner']),1)
        page=self.client.get(reverse('diet_template_preview',args=[self.ramadan.pk]))
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'برنامه ماه رمضان')
        self.assertContains(page,'سحری')
        self.assertContains(page,'افطار')
        self.assertContains(page,'یک لیوان شیر یا ماست')
        self.assertContains(page,'متن اصلی برنامه و نکات پزشک')
        self.assertNotContains(page,'ناهار</strong>')

    def test_quota_and_free_foods_can_be_edited_without_overwriting_source(self):
        original=self.ram_source.body
        response=self.client.post(reverse('treatment_content_manage',args=[self.ramadan.pk]),{
            'action':'save_diet_template','presentation_template':'ramadan',
            'quota_text':'روزانه دو عدد خرما','free_foods_text':'خیار و کاهو',
            'diet_notes_text':'توضیح مخصوص برنامه',
        },follow=True)
        self.assertEqual(response.status_code,200)
        self.ram.refresh_from_db()
        self.ram_source.refresh_from_db()
        self.assertEqual(self.ram_source.body,original)
        self.assertEqual(self.ram.quota_text,'روزانه دو عدد خرما')
        self.assertContains(self.client.get(reverse('diet_template_preview',args=[self.ramadan.pk])),'خیار و کاهو')
        self.assertContains(self.client.get(reverse('diet_template_preview',args=[self.ramadan.pk])),'روزانه دو عدد خرما')

    def test_ramadan_specific_meal_edit_does_not_change_other_days(self):
        original=self.ram_source.body
        response=self.client.post(reverse('treatment_content_manage',args=[self.ramadan.pk]),{
            'action':'save_template_meal','template_day':'2','template_slot':'suhoor',
            'template_body':'سحری اختصاصی روز یکشنبه','template_kcal':'',
        },follow=True)
        self.assertEqual(response.status_code,200)
        self.ram_source.refresh_from_db()
        self.assertEqual(self.ram_source.body,original)
        week=build_ramadan_week(self.ram.sections.prefetch_related('media'))
        self.assertTrue(any('دو عدد خرما' in c['body'] for c in week[1]))
        self.assertTrue(any('اختصاصی روز یکشنبه' in c['body'] for c in week[2]))
        self.assertFalse(any('اختصاصی روز یکشنبه' in c['body'] for c in week[1]))

    def test_two_unexplained_templates_remain_unconverted(self):
        self.assertEqual(self.other.presentation_template,'legacy')
        self.assertEqual(
            self.client.get(reverse('diet_template_preview',args=[self.keto.pk])).status_code,404
        )
        self.assertEqual(
            self.client.get(reverse('diet_daily_preview',args=[self.keto.pk])).status_code,200
        )
        self.client.logout()
        self.assertEqual(
            self.client.get(reverse('diet_template_preview',args=[self.ramadan.pk])).status_code,302
        )

    def test_pilot_assignment_data_migration_only_known_titles(self):
        self.week.presentation_template='legacy'
        self.ram.presentation_template='legacy'
        self.week.save(update_fields=['presentation_template'])
        self.ram.save(update_fields=['presentation_template'])
        migration=import_module('core.migrations.0090_two_diet_templates')
        class Editor: connection=connection
        migration.assign_known_pilot_templates(apps,Editor())
        self.week.refresh_from_db()
        self.ram.refresh_from_db()
        self.other.refresh_from_db()
        self.assertEqual(self.week.presentation_template,'weekly')
        self.assertEqual(self.ram.presentation_template,'ramadan')
        self.assertEqual(self.other.presentation_template,'legacy')
