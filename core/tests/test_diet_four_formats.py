"""Four diet templates: 13-day keto, illustrated text, new draft, safe CRM import."""
from unittest.mock import patch
from importlib import import_module
from django.contrib.auth.models import User
from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import (
    TreatmentCatalogItem,TreatmentRichContent,TreatmentRichSection,TreatmentRichMedia,TreatmentDietDayAudio,
)
from core.diet_thirteen_plan import build_thirteen_days,get_explicit_day
from core.treatment_content_import import extract_live_diet_html


def sample_crm_html(title='برنامه غذایی'):
    return (
        '<html><body><main><section><h2>عنوان</h2></section>'
        '<section class="mt-10"><div class="flex-1">'
        '<h2>برنامه غذایی</h2><main>'
        '<p>روز ۱</p><p>صبحانه</p><p>دو عدد خرما</p>'
        '<p>ناهار</p><p>مرغ و سالاد</p>'
        '<p>روز ۲</p><p>صبحانه</p><p>تخم مرغ</p>'
        '</main></div></section>'
        '<section><div class="flex-1"><h2>سهمیه و مواد آزاد</h2>'
        '<p>سیب و خیار آزاد</p></div>'
        '<div class="flex-1"><h2>توضیحات</h2>'
        '<p>مقدار تاییدشده پزشک</p></div></section></main></body></html>'
    ).encode('utf-8')


class FourDietFormatsTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('four-admin','four@example.org','testpass')
        self.client.force_login(self.admin)
        self.keto=TreatmentCatalogItem.objects.create(category='diet',name='Keto-Fast')
        self.apple=TreatmentCatalogItem.objects.create(category='diet',name='Sib-150')
        self.keto_content=TreatmentRichContent.objects.create(master_item=self.keto,presentation_template='thirteen')
        self.apple_content=TreatmentRichContent.objects.create(master_item=self.apple,presentation_template='text')

    def test_13_days_and_day_14_visit_not_a_fourteenth_menu(self):
        source=TreatmentRichSection.objects.create(
            content=self.keto_content,title='برنامه غذایی',
            body='روز ۱\nناشتا\nیک لیوان آب\nصبحانه\nنان\nناهار\nمرغ\n'
                 'روز ۲\nناشتا\nآب گرم\nناهار\nتخم مرغ\n'
                 'روز ۱۳\nصبحانه\nپنیر و گردو',
        )
        days,unassigned=build_thirteen_days([source])
        self.assertEqual(len(days),13)
        self.assertEqual(days[1][0]['body'],'یک لیوان آب')
        self.assertEqual(days[2][-1]['body'],'تخم مرغ')
        self.assertIn('پنیر و گردو',[x['body'] for x in days[13]])
        self.assertFalse(days[3])
        page=self.client.get(reverse('diet_template_preview',args=[self.keto.pk]))
        self.assertEqual(page.status_code,200)
        self.assertContains(page,'data-day=',count=13)
        self.assertContains(page,'روز ۱۴')
        self.assertContains(page,'مراجعه به مطب')
        self.assertContains(page,'touchstart')
        self.assertNotContains(page,'روز ۱۴</h2>')

    def test_thirteen_distinct_mint_plaques_show_one_day_at_a_time(self):
        TreatmentRichSection.objects.create(
            content=self.keto_content,title='برنامه غذایی',
            body='روز ۱\nصبحانه\nتخم مرغ\nروز ۲\nناهار\nسالاد',
        )
        response=self.client.get(reverse('diet_template_preview',args=[self.keto.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'data-select-day=',count=13)
        self.assertContains(response,'role="tab"',count=13)
        self.assertContains(response,'role="tabpanel"',count=13)
        plaque_markup=response.content.decode('utf-8').split(
            '<nav class="day-selector"',1
        )[1].split('</nav>',1)[0]
        self.assertEqual(plaque_markup.count('aria-selected="true"'),1)
        self.assertEqual(plaque_markup.count('aria-selected="false"'),12)
        self.assertContains(response,'grid-template-columns:repeat(7,minmax(0,1fr))')
        self.assertContains(response,'.day-plaque[aria-selected="true"]{background:#cee9d6')
        self.assertContains(response,'page.hidden=!chosen')
        self.assertContains(response,'show(active+1)')
        self.assertContains(response,'show(active-1)')
        self.assertContains(response,'dx>0?1:-1')
        self.assertNotContains(response,'diet-day-picker')
        self.assertNotContains(response,'background:#175a42')
        self.assertNotContains(response,'data-select-day="14"')
        self.assertContains(response,'روز ۱')
        self.assertContains(response,'روز ۱۳')
        self.assertNotContains(response,'روز ۱ از ۱۳')
        self.assertContains(response,'برنامه غذایی روز انتخاب‌شده')

    def test_thirteen_skips_unfilled_breakfast_snacks_and_other_meals(self):
        # Blank editor slots should never create empty cards or stock photos.
        for slot,text in (
            ('fasting',''),('breakfast','   '),('snack_am',''),
            ('pre_lunch',''),('snack_pm','   '),('dinner',''),
        ):
            TreatmentRichSection.objects.create(
                content=self.keto_content,title=slot,
                meal_slot=slot,day_number=1,body=text,
            )
        TreatmentRichSection.objects.create(
            content=self.keto_content,title='ناهار',
            meal_slot='lunch',day_number=1,body='مرغ کبابی و سالاد',
        )
        TreatmentRichSection.objects.create(
            content=self.keto_content,title='میان‌وعده صبح',
            meal_slot='snack_am',day_number=2,body='یک عدد سیب',
        )
        response=self.client.get(reverse('diet_template_preview',args=[self.keto.pk]))
        self.assertEqual(response.status_code,200)
        html=response.content.decode('utf-8')
        day1=html.split('id="day-1"',1)[1].split('</section>',1)[0]
        day2=html.split('id="day-2"',1)[1].split('</section>',1)[0]
        self.assertEqual(day1.count('<article class="meal">'),1)
        self.assertIn('مرغ کبابی و سالاد',day1)
        self.assertNotIn('میان‌وعده صبح',day1)
        self.assertNotIn('عصرانه',day1)
        self.assertNotIn('meal-snack-am.svg',day1)
        self.assertNotIn('meal-snack-pm.svg',day1)
        self.assertIn('میان‌وعده صبح',day2)
        self.assertIn('یک عدد سیب',day2)
        day3=html.split('id="day-3"',1)[1].split('</section>',1)[0]
        self.assertNotIn('<article class="meal">',day3)
        self.assertIn('برنامه غذایی این روز هنوز ثبت نشده است.',day3)
        self.assertNotIn('class="empty"',html)

    def test_thirteen_mobile_presentation_matches_orange_structure_but_uses_own_media(self):
        self.keto_content.cover_external_url='https://example.org/keto-cover.jpg'
        self.keto_content.slogan='هر روز، فرصتی تازه برای سلامتی'
        self.keto_content.slogan_external_url='https://example.org/keto-smile.jpg'
        self.keto_content.audio_external_url='https://example.org/keto-general.mp3'
        self.keto_content.save()
        TreatmentDietDayAudio.objects.create(
            content=self.keto_content,day_number=2,
            external_url='https://example.org/keto-day2.mp3',
        )
        section=TreatmentRichSection.objects.create(
            content=self.keto_content,title='صبحانه',
            meal_slot='breakfast',day_number=1,body='تخم‌مرغ و پنیر مخصوص کتو',
        )
        TreatmentRichMedia.objects.create(
            section=section,kind='image',
            original_url='https://example.org/keto-breakfast.jpg',
        )
        response=self.client.get(reverse('diet_template_preview',args=[self.keto.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'رژیم کتو فست')
        self.assertContains(response,'https://example.org/keto-cover.jpg')
        self.assertContains(response,'https://example.org/keto-smile.jpg')
        self.assertContains(response,'هر روز، فرصتی تازه برای سلامتی')
        self.assertContains(response,'صدای جادویی')
        self.assertContains(response,'https://example.org/keto-day2.mp3')
        self.assertContains(response,'https://example.org/keto-general.mp3')
        self.assertContains(response,'https://example.org/keto-breakfast.jpg')
        self.assertContains(response,'data-day=',count=13)
        self.assertContains(response,'روز ۱۴')
        self.assertContains(response,'درخواست ویزیت')
        self.assertContains(response,'dx>0?1:-1')
        self.assertContains(response,'روز بعد')
        self.assertContains(response,'روز قبل')
        self.assertContains(response,'.day-sheet{display:none}')
        self.assertContains(response,'href="'+reverse('customer_club')+'"')
        self.assertContains(response,'href="'+reverse('customer_request',args=['device'])+'"')
        self.assertContains(response,'href="'+reverse('customer_request',args=['visit'])+'"')
        self.assertNotContains(response,'orange-slogan-woman.webp')
        self.assertNotContains(response,'لاغری یعنی زندگی بهتر')
        self.assertNotContains(response,'https://example.org/orange-cover.jpg')
        self.assertNotContains(response,'۳۲۰ کالری')

    def test_thirteen_without_slogan_or_audio_displays_no_orange_fallback(self):
        TreatmentRichSection.objects.create(
            content=self.keto_content,title='برنامه غذایی',
            body='روز ۱\nصبحانه\nنان و پنیر\nروز ۱۳\nشام\nسوپ',
        )
        response=self.client.get(reverse('diet_template_preview',args=[self.keto.pk]))
        self.assertEqual(response.status_code,200)
        self.assertNotContains(response,'class="slogan"')
        self.assertContains(response,'فایل صوتی هنوز ثبت نشده است.')
        self.assertContains(response,'روز ۱۳')
        self.assertNotContains(response,'روز 13 از ۱۳')
        self.assertNotContains(response,'روز ۱۴</h2>')
        self.assertContains(response,'نان و پنیر')
        self.assertContains(response,'سوپ')
        self.assertNotContains(response,'orange-slogan-woman.webp')

    def test_keto_starting_with_breakfast_is_one_complete_first_day(self):
        source=TreatmentRichSection.objects.create(
            content=self.keto_content,title='برنامه غذایی',
            body='صبحانه\nدو عدد تخم مرغ\nناهار\nمرغ و سالاد\n'
                 'شام\nسوپ کتو\nروز ۲\nصبحانه\nپنیر و گردو',
        )
        direct,unassigned=build_thirteen_days(
            [source],infer_first_keto_day=True,
        )
        self.assertEqual(
            [item['slot'] for item in direct[1]],
            ['breakfast','lunch','dinner'],
        )
        self.assertEqual(
            [item['body'] for item in direct[1]],
            ['دو عدد تخم مرغ','مرغ و سالاد','سوپ کتو'],
        )
        self.assertEqual([item['body'] for item in direct[2]],['پنیر و گردو'])
        self.assertFalse(direct[3])
        self.assertFalse(unassigned)
        self.assertNotIn('snack_am',[card['slot'] for card in direct[1]])
        self.assertNotIn('snack_pm',[card['slot'] for card in direct[1]])
        legacy,unassigned=build_thirteen_days([source])
        self.assertFalse(legacy[1])
        self.assertIn('صبحانه',unassigned[0]['body'])

        page=self.client.get(reverse('diet_template_preview',args=[self.keto.pk]))
        self.assertEqual(page.status_code,200)
        html=page.content.decode('utf-8')
        first=html.split('id="day-1"',1)[1].split('</section>',1)[0]
        self.assertIn('دو عدد تخم مرغ',first)
        self.assertIn('مرغ و سالاد',first)
        self.assertIn('سوپ کتو',first)
        self.assertNotIn('meal-snack-am.svg',first)
        self.assertNotIn('meal-snack-pm.svg',first)

    def test_keto_without_day_headers_can_be_only_day_one_if_breakfast_is_first(self):
        source=TreatmentRichSection.objects.create(
            content=self.keto_content,title='برنامه غذایی',
            body='صبحانه\nاملت\nناهار\nماهی\nشام\nسالاد',
        )
        days,unassigned=build_thirteen_days([source],infer_first_keto_day=True)
        self.assertEqual([row['slot'] for row in days[1]],['breakfast','lunch','dinner'])
        self.assertFalse(days[2])
        self.assertFalse(unassigned)

    def test_non_breakfast_prose_without_day_heading_remains_unassigned(self):
        source=TreatmentRichSection.objects.create(
            content=self.keto_content,title='برنامه غذایی',
            body='ابتدا شرایط پزشک بررسی شود\nصبحانه\nتخم‌مرغ',
        )
        days,unassigned=build_thirteen_days([source],infer_first_keto_day=True)
        self.assertFalse(days[1])
        self.assertEqual(len(unassigned),1)
        self.assertIn('ابتدا شرایط پزشک',unassigned[0]['body'])

    def test_thirteen_persian_day_heading_without_guessing_unmapped_text(self):
        self.assertEqual(get_explicit_day('روز ۱۳: صبحانه'),(13,'صبحانه'))
        self.assertEqual(get_explicit_day('روز سیزدهم: ناهار'),(13,'ناهار'))
        self.assertIsNone(get_explicit_day('روز ۱۴: ناهار'))
        source=TreatmentRichSection.objects.create(
            content=self.keto_content,title='برنامه غذایی',
            body='این متن بدون شماره روز وارد شده است\nصبحانه\nدو عدد سیب',
        )
        days,unmapped=build_thirteen_days([source])
        self.assertTrue(all(not values for values in days.values()))
        self.assertEqual(len(unmapped),1)
        preview=self.client.get(reverse('diet_template_preview',args=[self.keto.pk]))
        self.assertContains(preview,'این متن بدون شماره روز وارد شده است')

    def test_different_days_can_be_edited_without_touching_original(self):
        source=TreatmentRichSection.objects.create(
            content=self.keto_content,title='برنامه غذایی',
            body='روز ۱\nصبحانه\nنان و پنیر\nروز ۲\nصبحانه\nجو دوسر',
        )
        request=self.client.post(reverse('treatment_content_manage',args=[self.keto.pk]),{
            'action':'save_template_meal','template_day':'2','template_slot':'breakfast',
            'template_body':'صبحانه اصلاح‌شده روز ۲','template_kcal':'',
        },follow=True)
        self.assertEqual(request.status_code,200)
        source.refresh_from_db()
        self.assertIn('جو دوسر',source.body)
        days,_=build_thirteen_days(self.keto_content.sections.prefetch_related('media'))
        self.assertIn('نان و پنیر',[x['body'] for x in days[1]])
        self.assertIn('صبحانه اصلاح‌شده روز ۲',[x['body'] for x in days[2]])
        bad=self.client.post(reverse('treatment_content_manage',args=[self.keto.pk]),{
            'action':'save_template_meal','template_day':'14','template_slot':'breakfast',
            'template_body':'نباید ذخیره شود',
        },follow=True)
        self.assertEqual(bad.status_code,200)
        self.assertFalse(self.keto_content.sections.filter(body='نباید ذخیره شود').exists())

    def test_text_sections_are_phone_pages_and_can_add_edit_reorder_delete(self):
        original=TreatmentRichSection.objects.create(
            content=self.apple_content,title='توضیحات روزه سیب',body='روزانه سیب مصرف شود',sort_order=10,
        )
        page=self.client.get(reverse('diet_template_preview',args=[self.apple.pk]))
        self.assertContains(page,'توضیحات روزه سیب')
        self.assertContains(page,'روزانه سیب مصرف شود')
        self.assertContains(page,'touchstart')
        self.assertContains(page,'page-counter')
        result=self.client.post(reverse('treatment_content_manage',args=[self.apple.pk]),{
            'action':'add_text_page','page_title':'روش مصرف','page_body':'توضیح دقیق مورد دوم',
        },follow=True)
        self.assertEqual(result.status_code,200)
        added=self.apple_content.sections.get(is_editor_page=True)
        self.assertEqual(added.meal_slot,'other')
        modify=self.client.post(reverse('treatment_content_manage',args=[self.apple.pk]),{
            'action':'save_text_page','section_id':added.pk,
            'page_title':'صفحه دوم','page_body':'توضیح ویرایش‌شده','page_order':'1',
        },follow=True)
        self.assertEqual(modify.status_code,200)
        added.refresh_from_db()
        self.assertEqual(added.sort_order,1)
        self.assertEqual(added.body,'توضیح ویرایش‌شده')
        view=self.client.get(reverse('diet_template_preview',args=[self.apple.pk]))
        self.assertContains(view,'توضیح ویرایش‌شده')
        removed=self.client.post(reverse('treatment_content_manage',args=[self.apple.pk]),{
            'action':'delete_text_page','section_id':added.pk,
        },follow=True)
        self.assertEqual(removed.status_code,200)
        self.assertFalse(TreatmentRichSection.objects.filter(pk=added.pk).exists())
        self.assertTrue(TreatmentRichSection.objects.filter(pk=original.pk).exists())

    def test_manager_creates_new_inactive_diet_with_chosen_template(self):
        out=self.client.post(reverse('treatment_content_library'),{
            'action':'create_diet','diet_name':'برنامه خام‌خواری تست','diet_template':'text',
        },follow=True)
        self.assertEqual(out.status_code,200)
        item=TreatmentCatalogItem.objects.get(name='برنامه خام‌خواری تست')
        self.assertFalse(item.is_active)
        self.assertFalse(item.rich_content.is_active)
        self.assertEqual(item.rich_content.presentation_template,'text')
        duplicate=self.client.post(reverse('treatment_content_library'),{
            'action':'create_diet','diet_name':'برنامه خام‌خواری تست','diet_template':'weekly',
        },follow=True)
        self.assertEqual(duplicate.status_code,200)
        self.assertEqual(TreatmentCatalogItem.objects.filter(name='برنامه خام‌خواری تست').count(),1)
        self.assertNotIn('برنامه خام‌خواری تست', [
            row.master_item.name for row in TreatmentRichContent.objects.filter(is_active=True)
        ])

    def test_live_crm_parse_and_safe_get_only_new_content(self):
        parsed=extract_live_diet_html(sample_crm_html(),'Keto-Fast')
        self.assertEqual(parsed['title'],'Keto-Fast')
        self.assertEqual(parsed['sections'][0]['title'],'برنامه غذایی')
        from core.treatment_crm_diet_transfer import import_one_crm_diet
        with patch('core.treatment_crm_diet_transfer._read_capped',
                   return_value=(sample_crm_html(),'text/html; charset=utf-8')) as get:
            out=import_one_crm_diet(self.keto)
            self.assertEqual(out['sections'],3)
            self.assertEqual(get.call_count,1)
            args=get.call_args.args
            self.assertIn('diet1.php?d=Keto-Fast&c=1',args[0])
        self.keto_content.refresh_from_db()
        self.assertFalse(self.keto_content.is_active)
        self.assertEqual(self.keto_content.presentation_template,'thirteen')
        first=self.keto_content.sections.get(title='برنامه غذایی')
        self.assertIn('دو عدد خرما',first.body)
        # Repeated import cannot replace text or editor changes.
        first.body='ویرایش ادمین، حفظ شود'
        first.save(update_fields=['body'])
        with self.assertRaises(ValueError):
            import_one_crm_diet(self.keto)
        first.refresh_from_db()
        self.assertEqual(first.body,'ویرایش ادمین، حفظ شود')

    def test_crm_http_failure_does_not_change_database(self):
        from urllib.error import URLError
        from core.treatment_crm_diet_transfer import import_one_crm_diet
        with patch('core.treatment_crm_diet_transfer._read_capped',side_effect=URLError('test offline')):
            with self.assertRaises(ValueError):
                import_one_crm_diet(self.keto)
        self.assertFalse(self.keto_content.sections.exists())

    def test_migration_assigns_only_remaining_two_pilots(self):
        self.keto_content.presentation_template='legacy'
        self.apple_content.presentation_template='legacy'
        self.keto_content.save(update_fields=['presentation_template'])
        self.apple_content.save(update_fields=['presentation_template'])
        migration=import_module('core.migrations.0091_four_diet_formats')
        class Editor: connection=connection
        migration.assign_remaining_pilots(apps,Editor())
        self.keto_content.refresh_from_db()
        self.apple_content.refresh_from_db()
        self.assertEqual(self.keto_content.presentation_template,'thirteen')
        self.assertEqual(self.apple_content.presentation_template,'text')
