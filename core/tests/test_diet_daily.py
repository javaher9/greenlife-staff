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
        self.assertEqual(self.client.get(reverse('diet_daily_preview',args=[self.item.pk])+'?day=1').status_code,404)

    def test_daily_audio_and_permissions(self):
        TreatmentRichSection.objects.create(content=self.content,title='ناهار',body='محتوای واقعی')
        TreatmentDietDayAudio.objects.create(content=self.content,day_number=1,external_url='https://example.org/voice.mp3')
        page=self.client.get(reverse('diet_daily_preview',args=[self.item.pk]))
        self.assertContains(page,'https://example.org/voice.mp3')
        self.client.logout()
        response=self.client.get(reverse('diet_daily_preview',args=[self.item.pk]))
        self.assertEqual(response.status_code,302)
