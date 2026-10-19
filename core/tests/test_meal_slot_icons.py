"""Neutral meal-time icon mapping is shared by every scheduled diet, not its foods."""
from pathlib import Path
from xml.etree import ElementTree as ET

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.diet_meal_icons import MEAL_ICON_NAMES, meal_illustration_url
from core.models import (
    TreatmentCatalogItem, TreatmentRichContent,
    TreatmentRichSection, TreatmentRichMedia,
)


class MealSlotIconAssetTests(SimpleTestCase):
    def test_each_supported_meal_slot_has_a_non_food_svg_icon(self):
        expected={
            'fasting','breakfast','snack_am','pre_lunch','lunch',
            'snack_pm','pre_dinner','dinner','bedtime','other',
            'pre_suhoor','suhoor','iftar','after_iftar',
        }
        self.assertTrue(expected.issubset(set(MEAL_ICON_NAMES)))
        icon_dir=Path(__file__).resolve().parents[1]/'static'/'core'/'diet'
        for slot,name in MEAL_ICON_NAMES.items():
            with self.subTest(slot=slot):
                icon_file=icon_dir/('meal-'+name+'.svg')
                self.assertTrue(icon_file.exists(),str(icon_file))
                svg=ET.parse(icon_file).getroot()
                self.assertEqual(svg.tag,'{http://www.w3.org/2000/svg}svg')
                self.assertIn('meal-'+name+'.svg',meal_illustration_url(slot))
                self.assertNotIn('<image',icon_file.read_text(encoding='utf-8'))

    def test_snacks_show_10_and_16_hours_and_fasting_has_drop(self):
        icons=Path(__file__).resolve().parents[1]/'static'/'core'/'diet'
        morning=(icons/'meal-snack-am.svg').read_text(encoding='utf-8')
        afternoon=(icons/'meal-snack-pm.svg').read_text(encoding='utf-8')
        fasting=(icons/'meal-fasting.svg').read_text(encoding='utf-8')
        self.assertIn('۱۰:۰۰',morning)
        self.assertIn('۱۶:۰۰',afternoon)
        self.assertNotIn('<text',fasting)
        self.assertIn('قطره آب و برگ',fasting)
        self.assertIn('طلوع خورشید',(icons/'meal-breakfast.svg').read_text(encoding='utf-8'))


class MealSlotIconPresentationTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser(
            'icon-admin','icon-admin@example.org','strong-pass',
        )
        self.client.force_login(self.admin)

    def add_food(self,code,kind,slot,body,photo='https://example.org/food-picture.jpg'):
        item=TreatmentCatalogItem.objects.create(category='diet',name=code)
        content=TreatmentRichContent.objects.create(
            master_item=item,presentation_template=kind,
        )
        section=TreatmentRichSection.objects.create(
            content=content,title='وعده غذایی',body=body,
            meal_slot=slot,day_number=1,
        )
        TreatmentRichMedia.objects.create(
            section=section,kind='image',original_url=photo,
        )
        return item,section

    def test_all_weekly_thirteen_ramadan_render_icons_not_stored_food_images(self):
        cases=(
            ('Por-150','weekly','breakfast','meal-breakfast.svg'),
            ('Weekly-Icon-Test','weekly','snack_am','meal-snack-am.svg'),
            ('Thirteen-Icon-Test','thirteen','snack_pm','meal-snack-pm.svg'),
            ('Ramadan-Icon-Test','ramadan','suhoor','meal-suhoor.svg'),
            ('Ramadan-Iftar-Test','ramadan','iftar','meal-iftar.svg'),
        )
        for code,kind,slot,icon in cases:
            with self.subTest(code=code):
                item,section=self.add_food(code,kind,slot,'فقط میوه تازه')
                url=reverse('diet_template_preview',args=[item.pk])
                response=self.client.get(url+'?day=1' if code=='Por-150' else url)
                self.assertEqual(response.status_code,200)
                self.assertContains(response,icon)
                self.assertContains(response,'نماد زمانی')
                self.assertNotContains(response,'food-picture.jpg')
                self.assertIn('فقط میوه تازه',response.content.decode('utf-8'))
                self.assertTrue(TreatmentRichMedia.objects.filter(
                    section=section,original_url='https://example.org/food-picture.jpg',
                ).exists())

    def test_generic_daily_meal_card_uses_same_icon_and_preserves_media(self):
        item,section=self.add_food(
            'Standalone-Daily-Test','legacy','breakfast','دو عدد میوه',
        )
        response=self.client.get(reverse('diet_daily_preview',args=[item.pk])+'?day=1')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'meal-breakfast.svg')
        self.assertNotContains(response,'food-picture.jpg')
        self.assertTrue(section.media.exists())
