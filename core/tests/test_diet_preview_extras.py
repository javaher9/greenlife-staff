"""Regression for diet note/quota dedup and headphone prompt."""
from types import SimpleNamespace
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from core.diet_extras_display import prepare_diet_extras
from core.diet_week_plan import build_orange_week
from core.models import TreatmentCatalogItem,TreatmentRichContent,TreatmentRichSection


class DietPreviewExtrasTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_superuser('extra-admin','extra@example.org','password')
        self.client.force_login(self.user)
        # Use a generic weekly diet; Por-150 intentionally uses its separate pilot view.
        item=TreatmentCatalogItem.objects.create(category='diet',name='Test-Weekly-Extras')
        self.content=TreatmentRichContent.objects.create(
            master_item=item,presentation_template='weekly',
            audio_external_url='https://example.org/valid-original-audio.mp3',
        )
        self.food=TreatmentRichSection.objects.create(
            content=self.content,title='برنامه غذایی',sort_order=10,
            body='ناشتا\nیک لیوان آب\nصبحانه\nدو عدد پرتقال',
        )
        self.quota=TreatmentRichSection.objects.create(
            content=self.content,title='سهمیه و مواد آزاد',sort_order=20,
            body='روغن زیتون سه قاشق\nخرما دو عدد',
        )
        self.notes=TreatmentRichSection.objects.create(
            content=self.content,title='توضیحات',sort_order=30,
            body='آب کافی میل شود',
        )
        self.same_notes=TreatmentRichSection.objects.create(
            content=self.content,title='توضيحات',sort_order=40,
            body='آب کافی میل شود',
        )
        self.extra_notes=TreatmentRichSection.objects.create(
            content=self.content,title='توضیحات',sort_order=50,
            body='پیاده‌روی ملایم',
        )

    def test_notes_are_not_meal_cards_and_have_one_notes_panel(self):
        week=build_orange_week(self.content.sections.prefetch_related('media'))
        for cards in week.values():
            self.assertFalse(any(c['slot']=='other' for c in cards))
        result=self.client.get(reverse('diet_template_preview',args=[self.content.master_item_id]))
        self.assertEqual(result.status_code,200)
        text=result.content.decode('utf8')
        self.assertEqual(text.count('<h2>توضیحات</h2>'),1)
        self.assertEqual(text.count('آب کافی میل شود'),1)
        self.assertEqual(text.count('پیاده‌روی ملایم'),1)
        self.assertEqual(text.count('<h2>سهمیه و مواد آزاد</h2>'),1)
        self.assertEqual(text.count('روغن زیتون سه قاشق'),1)
        self.assertIn('🎧',text)
        self.assertNotIn('با هدفون گوش دهید',text)

    def test_exact_duplicate_is_hidden_but_distinct_advice_preserved(self):
        sections=[
            SimpleNamespace(meal_slot='other',title='توضيحات',body='یک دستور پزشکی'),
            SimpleNamespace(meal_slot='other',title='توضیحات',body='یک دستور پزشکی'),
            SimpleNamespace(meal_slot='other',title='توضیحات',body='دستور دیگری'),
        ]
        extras=prepare_diet_extras(sections)
        self.assertEqual(len(extras),1)
        self.assertEqual(extras[0].title,'توضیحات')
        self.assertEqual(extras[0].body,'یک دستور پزشکی\n\nدستور دیگری')

    def test_original_source_and_other_diets_unmodified(self):
        source=self.notes.body
        self.client.get(reverse('diet_template_preview',args=[self.content.master_item_id]))
        self.notes.refresh_from_db()
        self.assertEqual(source,self.notes.body)
