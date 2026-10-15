from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection, TreatmentDietDayAudio


class DailyDietPresentationTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('diet-tester','diet@example.com','test-pass')
        self.item=TreatmentCatalogItem.objects.create(category='diet',name='Por-150')
        self.content=TreatmentRichContent.objects.create(master_item=self.item,is_active=True)
        self.client.force_login(self.admin)

    def test_old_content_is_shown_without_invented_calories(self):
        TreatmentRichSection.objects.create(
            content=self.content,title='برنامه غذایی',body='صبحانه\nنان و پنیر موجود در نسخه اصلی',
            day_number=1,
        )
        response=self.client.get(reverse('diet_daily_preview',args=[self.item.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'رژیم پرتقال')
        self.assertContains(response,'لاغری یعنی زندگی بهتر')
        self.assertContains(response,'صدای جادویی')
        self.assertContains(response,'با هدفون گوش دهید')
        self.assertContains(response,'نان و پنیر موجود در نسخه اصلی')
        self.assertNotContains(response,'۳۲۰ کالری')
        self.assertNotContains(response,'شبکه فروش')

    def test_editor_can_save_day_meal_and_slogan(self):
        section=TreatmentRichSection.objects.create(content=self.content,title='صبحانه',body='نان موجود',sort_order=10)
        response=self.client.post(reverse('treatment_content_manage',args=[self.item.pk]),{
            'action':'update_content','slogan':'لاغری یعنی زندگی بهتر','display_title':'رژیم پرتقال',
            'hero_subtitle':'برنامه غذایی پرتقال','intro_warning':'',
            'cover_external_url':'','audio_external_url':'','slogan_external_url':'',
        })
        self.assertEqual(response.status_code,302)
        self.content.refresh_from_db()
        self.assertEqual(self.content.slogan,'لاغری یعنی زندگی بهتر')
        response=self.client.post(reverse('treatment_content_manage',args=[self.item.pk]),{
            'action':'save_section','section_id':str(section.pk),'title':'صبحانه',
            'day_number':'2','meal_slot':'breakfast','estimated_kcal':'190',
            'sort_order':'10','body':'غذای واقعی روز دوم',
        })
        self.assertEqual(response.status_code,302)
        section.refresh_from_db()
        self.assertEqual(section.day_number,2)
        self.assertEqual(section.meal_slot,'breakfast')
        self.assertEqual(section.estimated_kcal,190)
        day=self.client.get(reverse('diet_daily_preview',args=[self.item.pk])+'?day=2')
        self.assertContains(day,'غذای واقعی روز دوم')
        self.assertContains(day,'190 کالری')
        # Seven calendar weekdays exist even when some are still empty.
        self.assertEqual(self.client.get(reverse('diet_daily_preview',args=[self.item.pk])+'?day=1').status_code,200)

    def test_daily_audio_and_permissions(self):
        TreatmentRichSection.objects.create(content=self.content,title='ناهار',body='محتوای واقعی')
        TreatmentDietDayAudio.objects.create(content=self.content,day_number=1,external_url='https://example.org/voice.mp3')
        page=self.client.get(reverse('diet_daily_preview',args=[self.item.pk])+'?day=1')
        self.assertContains(page,'https://example.org/voice.mp3')
        self.client.logout()
        response=self.client.get(reverse('diet_daily_preview',args=[self.item.pk]))
        self.assertEqual(response.status_code,302)


class OrangeOnlyWeekTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('orange-admin','orange@example.com','test-pass')
        self.client.force_login(self.admin)
        self.orange=TreatmentCatalogItem.objects.create(category='diet',name='Por-150')
        self.orange_content=TreatmentRichContent.objects.create(master_item=self.orange)
        self.other=TreatmentCatalogItem.objects.create(category='diet',name='Keto-Fast')
        self.other_content=TreatmentRichContent.objects.create(master_item=self.other)

    def test_original_weekday_lunch_and_dinner_are_separated(self):
        TreatmentRichSection.objects.create(
            content=self.orange_content,title='برنامه غذایی',
            body='صبحانه\nنان سبوس‌دار و پنیر\nناهار\nشنبه: مرغ با سبزیجات\nیکشنبه: ماهی و سالاد\nشام\nشنبه: سوپ\nیکشنبه: خوراک سبزیجات',
        )
        saturday=self.client.get(reverse('diet_daily_preview',args=[self.orange.pk])+'?day=1')
        sunday=self.client.get(reverse('diet_daily_preview',args=[self.orange.pk])+'?day=2')
        self.assertContains(saturday,'نان سبوس‌دار و پنیر')
        self.assertContains(sunday,'نان سبوس‌دار و پنیر')
        self.assertContains(saturday,'مرغ با سبزیجات')
        self.assertNotContains(saturday,'ماهی و سالاد')
        self.assertContains(sunday,'ماهی و سالاد')
        self.assertNotContains(sunday,'مرغ با سبزیجات')
        self.assertContains(saturday,'سوپ')
        self.assertContains(sunday,'خوراک سبزیجات')
        self.assertContains(saturday,'شنبه')
        self.assertContains(sunday,'یکشنبه')
        self.assertContains(saturday,'touchstart')

    def test_rotates_only_explicit_shared_breakfast_alternatives(self):
        TreatmentRichSection.objects.create(
            content=self.orange_content,title='برنامه غذایی',
            body='صبحانه\nنان و پنیر\nیا\nتخم مرغ و نان\nناهار\nشنبه: مرغ و برنج\nیکشنبه: ماهی',
        )
        saturday=self.client.get(reverse('diet_daily_preview',args=[self.orange.pk])+'?day=1')
        sunday=self.client.get(reverse('diet_daily_preview',args=[self.orange.pk])+'?day=2')
        self.assertContains(saturday,'نان و پنیر')
        self.assertNotContains(saturday,'تخم مرغ و نان')
        self.assertContains(sunday,'تخم مرغ و نان')
        self.assertNotContains(sunday,'نان و پنیر')

    def test_manual_weekday_override_leaves_source_untouched(self):
        source=TreatmentRichSection.objects.create(
            content=self.orange_content,title='برنامه غذایی',
            body='صبحانه\nنان و پنیر\nناهار\nشنبه: مرغ\nیکشنبه: ماهی',
        )
        response=self.client.post(reverse('treatment_content_manage',args=[self.orange.pk]),{
            'action':'save_orange_meal','week_day':'2','week_slot':'lunch',
            'week_body':'غذای جایگزین تایید شده پزشک','week_kcal':'275',
        })
        self.assertEqual(response.status_code,302)
        source.refresh_from_db()
        self.assertIn('یکشنبه: ماهی',source.body)
        saturday=self.client.get(reverse('diet_daily_preview',args=[self.orange.pk])+'?day=1')
        sunday=self.client.get(reverse('diet_daily_preview',args=[self.orange.pk])+'?day=2')
        self.assertContains(saturday,'مرغ')
        self.assertContains(sunday,'غذای جایگزین تایید شده پزشک')
        self.assertNotContains(sunday,'یکشنبه: ماهی')
        self.assertContains(sunday,'275 کالری')

    def test_other_diet_retains_original_single_day_template_and_disallows_week_editor(self):
        TreatmentRichSection.objects.create(
            content=self.other_content,title='برنامه غذایی',body='برنامه مخصوص کتو فست',
        )
        page=self.client.get(reverse('diet_daily_preview',args=[self.other.pk]))
        self.assertContains(page,'برنامه مخصوص کتو فست')
        self.assertNotContains(page,'touchstart')
        self.assertEqual(self.client.get(reverse('diet_daily_preview',args=[self.other.pk])+'?day=7').status_code,404)
        response=self.client.post(reverse('treatment_content_manage',args=[self.other.pk]),{
            'action':'save_orange_meal','week_day':'2','week_slot':'lunch','week_body':'نباید ثبت شود',
        })
        self.assertEqual(response.status_code,403)
        self.assertFalse(TreatmentRichSection.objects.filter(content=self.other_content,body='نباید ثبت شود').exists())
