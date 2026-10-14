"""Regression for safe five-item MHTML import and rich-content doctor preview."""
from django.apps import apps
from django.db import connection
from importlib import import_module
from io import BytesIO
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from tempfile import TemporaryDirectory
from zipfile import ZipFile, ZIP_DEFLATED
import base64

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from core.models import (
    Branch, TreatmentCatalogItem, TreatmentRichContent, TreatmentRichSection,
    TreatmentRichMedia,
)
from core.treatment_content_import import APPROVED_ITEMS, extract_approved_samples
from core.treatment_content_layout import build_section_preview

IMG=base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAIAAAD91JpzAAAAFklEQVR4nGP8//8/AwMDEwMDAwMDAwAkBgMB/DXemwAAAABJRU5ErkJggg=='
)


def fake_mhtml(title,cat):
    part=MIMEMultipart('related')
    if cat=='diet':
        content=(
            '<body><main><section><h2>برنامه '+title+'</h2></section><div>'
            '<section class="mt-10"><div class="flex-1">'
            '<h2>برنامه غذایی</h2><main><p>متن اصلی '+title+'</p>'
            '<img src="http://crm.greenlifeclinics.com/sample.jpg"></main></div></section>'
            '<section><div class="flex-1"><h2>سهمیه و مواد آزاد</h2>'
            '<div>سهمیه واقعی نمونه</div></div>'
            '<div class="flex-1"><h2>توضیحات</h2>'
            '<div>توضیحات برنامه</div></div></section></div></main></body>'
        )
    else:
        content='<body>'
        for idx in range(2):
            content+=(
                f'<main><section><h2>{title if idx==0 else "بخش دوم"}</h2></section>'
                f'<section class="mt-10"><div class="flex-1"><h2>متن توصیه</h2>'
                f'<main><p>متن توصیه {idx}</p></main></div></section></main>'
            )
        content+='</body>'
    part.attach(MIMEText(content,'html','utf-8'))
    img=MIMEImage(IMG,'png')
    img.add_header('Content-Location','http://crm.greenlifeclinics.com/sample.jpg')
    part.attach(img)
    return part.as_bytes()


def fake_zip():
    memory=BytesIO()
    with ZipFile(memory,'w',ZIP_DEFLATED) as archive:
        for category,title in sorted(APPROVED_ITEMS):
            archive.writestr('samples/'+title+'.mhtml',fake_mhtml(title,category))
    return memory.getvalue()


class TreatmentContentSampleTests(TestCase):
    def setUp(self):
        self.media=TemporaryDirectory()
        self.settings_override=override_settings(MEDIA_ROOT=self.media.name)
        self.settings_override.enable()
        self.branch=Branch.objects.create(name='تست محتوا')
        self.admin=User.objects.create_superuser(
            username='mhtml-admin',password='StrongPass123',email='admin@example.com',
        )
        self.doctor=User.objects.create_user(username='mhtml-doctor',password='StrongPass123')
        self.doctor.profile.role='doctor'
        self.doctor.profile.branch=self.branch
        self.doctor.profile.save(update_fields=['role','branch'])
        self.manager=User.objects.create_user(username='mhtml-manager',password='StrongPass123')
        self.manager.profile.role='manager'
        self.manager.profile.branch=self.branch
        self.manager.profile.save(update_fields=['role','branch'])
        for category,title in APPROVED_ITEMS:
            TreatmentCatalogItem.objects.get_or_create(
                category=category,name=title,branch=None,
                defaults={'is_active':True,'created_by':self.admin},
            )
        self.data=fake_zip()

    def tearDown(self):
        self.settings_override.disable()
        self.media.cleanup()

    def _upload(self,replace=False):
        self.client.force_login(self.admin)
        return self.client.post(reverse('treatment_content_library'),{
            'archive':SimpleUploadedFile('samples.zip',self.data,content_type='application/zip'),
            'replace_existing':'1' if replace else '0',
        },follow=True)

    def test_import_has_five_masters_no_duplicates_and_ordered_sections(self):
        parsed=extract_approved_samples(self.data)
        self.assertEqual({(x['category'],x['title']) for x in parsed},APPROVED_ITEMS)
        before=TreatmentCatalogItem.objects.filter(
            category__in=('diet','recommendation'),
            name__in=[name for _,name in APPROVED_ITEMS],
        ).count()
        response=self._upload()
        self.assertEqual(response.status_code,200)
        self.assertEqual(TreatmentRichContent.objects.count(),5)
        self.assertEqual(TreatmentCatalogItem.objects.filter(
            category__in=('diet','recommendation'),
            name__in=[name for _,name in APPROVED_ITEMS],
        ).count(),before)
        advice=TreatmentRichContent.objects.get(master_item__name='نکات طلائی در لاغری')
        self.assertEqual(list(advice.sections.values_list('title',flat=True)),
                         ['نکات طلائی در لاغری','بخش دوم'])
        keto=TreatmentRichContent.objects.get(master_item__name='Keto-Fast')
        self.assertEqual(keto.sections.count(),3)
        media=TreatmentRichMedia.objects.get(section__content=keto,kind='image')
        self.assertTrue(media.uploaded_file)
        self.assertIn('sample',media.original_url)
        self.assertTrue(keto.is_active)

    def test_images_stay_inline_beside_corresponding_meal_after_import(self):
        parsed=extract_approved_samples(self.data)
        keto=next(x for x in parsed if x['title']=='Keto-Fast')
        meal=keto['sections'][0]
        self.assertEqual(len(meal['image_positions']),1)
        self.assertEqual(meal['image_positions'][0]['before_line'],1)
        self._upload()
        section=TreatmentRichSection.objects.get(
            content__master_item__name='Keto-Fast',title='برنامه غذایی',
        )
        medium=section.media.get(kind='image')
        self.assertEqual(medium.inline_before_line,1)
        preview=build_section_preview(section)
        self.assertEqual(len(preview.preview_rows),2)
        self.assertEqual(preview.preview_rows[0]['text'],'متن اصلی Keto-Fast')
        self.assertEqual(preview.preview_rows[1]['images'][0].pk,medium.pk)
        self.assertFalse(preview.footer_images)
        self.client.force_login(self.admin)
        response=self.client.get(
            reverse('treatment_content_preview',args=[section.content.master_item_id]),
        )
        self.assertContains(response,'class="meal-photos"')
        self.assertNotContains(response,'class="gallery"')

    def test_mobile_only_image_duplicate_stays_stored_but_is_not_displayed(self):
        self._upload()
        section=TreatmentRichSection.objects.get(
            content__master_item__name='Keto-Fast',title='برنامه غذایی',
        )
        existing=section.media.get(kind='image')
        duplicate=TreatmentRichMedia.objects.create(
            section=section,kind='image',sort_order=90,
            original_url=existing.original_url,inline_before_line=None,
            is_responsive_duplicate=True,
        )
        preview=build_section_preview(section)
        self.assertEqual(sum(len(row['images']) for row in preview.preview_rows),1)
        self.assertFalse(preview.footer_images)
        self.assertTrue(TreatmentRichMedia.objects.filter(pk=duplicate.pk).exists())

    def test_unpositioned_new_media_keeps_gallery_fallback(self):
        self._upload()
        section=TreatmentRichSection.objects.get(
            content__master_item__name='Keto-Fast',title='برنامه غذایی',
        )
        additional=TreatmentRichMedia.objects.create(
            section=section,kind='image',original_url='https://example.org/photo.jpg',
            sort_order=999,
        )
        preview=build_section_preview(section)
        self.assertIn(additional.pk,[media.pk for media in preview.footer_images])

    def test_backfill_repositions_old_import_without_changing_medical_text(self):
        from django.utils import timezone
        from core.models import TreatmentRichContent
        item=TreatmentCatalogItem.objects.get(name='Por-150',category='diet',branch=None)
        content=TreatmentRichContent.objects.create(master_item=item,origin='MHTML CRM')
        original='متن رژیم ثبت‌شده توسط پزشک'
        section=TreatmentRichSection.objects.create(
            content=content,title='برنامه غذایی',body=original,sort_order=10,
        )
        for i in range(11):
            TreatmentRichMedia.objects.create(
                section=section,kind='image',
                original_url=f'https://example.org/original/{i}.jpg',
                sort_order=(i+1)*10,
            )
        migration=import_module('core.migrations.0087_restore_treatment_inline_photos')
        class SchemaEditor:
            connection=connection
        migration.restore_photo_positions(apps,SchemaEditor())
        section.refresh_from_db()
        self.assertEqual(section.body,original)
        images=list(section.media.order_by('sort_order'))
        self.assertEqual([x.inline_before_line for x in images],
                         [0,3,6,9,12,None,29,32,35,None,52])
        self.assertEqual(sum(x.is_responsive_duplicate for x in images),2)
        self.assertEqual(section.media.count(),11)

    def test_repeat_upload_preserves_manual_edits(self):
        self._upload()
        row=TreatmentRichSection.objects.get(content__master_item__name='Keto-Fast',title='برنامه غذایی')
        row.body='اصلاح‌شده توسط ادمین'
        row.save()
        self._upload()
        row.refresh_from_db()
        self.assertEqual(row.body,'اصلاح‌شده توسط ادمین')
        self.assertEqual(TreatmentRichContent.objects.count(),5)

    def test_admin_can_edit_toggle_and_preview_and_doctor_cannot_edit(self):
        self._upload()
        content=TreatmentRichContent.objects.get(master_item__name='Keto-Fast')
        section=content.sections.first()
        self.client.force_login(self.admin)
        response=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'save_section','section_id':section.pk,'title':'برنامه اصلاح‌شده',
            'body':'متن ویرایش شده','sort_order':'7',
        },follow=True)
        self.assertEqual(response.status_code,200)
        section.refresh_from_db()
        self.assertEqual((section.title,section.body,section.sort_order),
                         ('برنامه اصلاح‌شده','متن ویرایش شده',7))
        self.client.force_login(self.doctor)
        self.assertEqual(self.client.get(reverse('treatment_content_manage',args=[content.master_item_id])).status_code,403)
        self.assertContains(self.client.get(reverse('treatment_content_preview',args=[content.master_item_id])), 'متن ویرایش شده')
        self.assertContains(self.client.get(reverse('treatment_content_browse')), 'Keto-Fast')
        self.client.force_login(self.admin)
        self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{'action':'toggle'})
        content.master_item.refresh_from_db()
        self.assertFalse(content.master_item.is_active)
        self.client.force_login(self.doctor)
        self.assertEqual(self.client.get(reverse('treatment_content_preview',args=[content.master_item_id])).status_code,404)
        from core.doctor_views import _catalog_options
        self.assertNotIn('Keto-Fast',[item['name'] for item in _catalog_options('diet',self.branch,())])

    def test_admin_media_upload_and_remove_persists(self):
        self._upload()
        content=TreatmentRichContent.objects.get(master_item__name='Keto-Fast')
        self.client.force_login(self.admin)
        response=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'upload','location':'cover','kind':'image',
            'media_file':SimpleUploadedFile('replacement.png',IMG,content_type='image/png'),
        },follow=True)
        self.assertEqual(response.status_code,200)
        content.refresh_from_db()
        self.assertTrue(content.cover_file)
        self.assertIn('replacement',content.cover_file.name)

        section=content.sections.first()
        response=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'upload','location':'section','kind':'audio','section_id':str(section.pk),
            'media_file':SimpleUploadedFile('sample.m4a',b'audio-only-test',content_type='audio/mp4'),
        },follow=True)
        self.assertEqual(response.status_code,200)
        medium=section.media.filter(kind='audio').first()
        self.assertIsNotNone(medium)
        self.assertTrue(medium.uploaded_file)
        response=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'remove_media','media_id':str(medium.pk),
        },follow=True)
        self.assertEqual(response.status_code,200)
        self.assertFalse(TreatmentRichMedia.objects.filter(pk=medium.pk).exists())

    def test_all_master_diets_have_direct_edit_and_unimported_remain_inactive(self):
        extra=TreatmentCatalogItem.objects.create(
            category='diet',name='رژیم آزمایشی تازه',created_by=self.admin,
        )
        self.client.force_login(self.admin)
        library=self.client.get(reverse('treatment_content_library'))
        self.assertContains(library,'رژیم آزمایشی تازه')
        self.assertContains(library,'✎ شروع ویرایش')
        response=self.client.post(reverse('treatment_content_library'),{
            'action':'start_edit','item_id':str(extra.pk),
        },follow=True)
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'مدیریت محتوا: رژیم آزمایشی تازه')
        content=TreatmentRichContent.objects.get(master_item=extra)
        self.assertFalse(content.is_active)
        self.assertEqual(content.sections.count(),0)
        self.assertTrue(extra.is_active)
        self.client.force_login(self.doctor)
        self.assertEqual(self.client.get(reverse('treatment_content_manage',args=[extra.pk])).status_code,403)

    def test_inline_meal_text_edit_is_atomic_and_persists_without_moving_images(self):
        self._upload()
        content=TreatmentRichContent.objects.get(master_item__name='Keto-Fast')
        section=content.sections.get(title='برنامه غذایی')
        before=list(section.media.values_list('pk','inline_before_line'))
        from core.treatment_content_edit_rows import inline_edit_rows
        first=inline_edit_rows(section)[0][0]
        self.client.force_login(self.admin)
        response=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'save_meal_line','section_id':section.pk,'line_number':first['index'],
            'line_signature':first['signature'],'line_text':'متن اصلاح‌شده صبحانه',
        },follow=True)
        self.assertEqual(response.status_code,200)
        section.refresh_from_db()
        self.assertIn('متن اصلاح‌شده صبحانه',section.body)
        self.assertEqual(list(section.media.values_list('pk','inline_before_line')),before)
        stale=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'save_meal_line','section_id':section.pk,'line_number':first['index'],
            'line_signature':first['signature'],'line_text':'بازنویسی اشتباه',
        },follow=True)
        self.assertEqual(stale.status_code,200)
        section.refresh_from_db()
        self.assertNotIn('بازنویسی اشتباه',section.body)
        self.client.force_login(self.manager)
        forbidden=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'save_meal_line','section_id':section.pk,'line_number':0,
            'line_text':'بدون مجوز',
        })
        self.assertEqual(forbidden.status_code,403)

    def test_replace_delete_and_readd_photo_acts_only_on_selected_meal(self):
        self._upload()
        content=TreatmentRichContent.objects.get(master_item__name='Keto-Fast')
        section=content.sections.get(title='برنامه غذایی')
        image=section.media.get(kind='image')
        original_count=TreatmentRichMedia.objects.count()
        original_text=section.body
        self.client.force_login(self.admin)
        replaced=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'replace_meal_image','media_id':image.pk,
            'meal_image':SimpleUploadedFile('updated-meal.png',IMG,content_type='image/png'),
        },follow=True)
        self.assertEqual(replaced.status_code,200)
        image.refresh_from_db()
        self.assertTrue(image.uploaded_file)
        self.assertIn('updated-meal',image.uploaded_file.name)
        self.assertEqual(TreatmentRichMedia.objects.count(),original_count)
        deleted=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'delete_meal_image','media_id':image.pk,
        },follow=True)
        self.assertEqual(deleted.status_code,200)
        self.assertFalse(TreatmentRichMedia.objects.filter(pk=image.pk).exists())
        added=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'add_meal_image','section_id':section.pk,'line_number':0,
            'meal_image':SimpleUploadedFile('new-breakfast.png',IMG,content_type='image/png'),
        },follow=True)
        self.assertEqual(added.status_code,200)
        self.assertTrue(section.media.filter(kind='image',inline_before_line=0).exists())
        section.refresh_from_db()
        self.assertEqual(section.body,original_text)

    def test_orange_week_image_replacement_and_delete_in_same_meal_panel(self):
        self._upload()
        content=TreatmentRichContent.objects.get(master_item__name='Por-150')
        self.client.force_login(self.admin)
        response=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'save_orange_meal','week_day':'1','week_slot':'lunch',
            'week_body':'ناهار: مرغ و سالاد','week_kcal':'',
            'week_image':SimpleUploadedFile('orange-lunch.png',IMG,content_type='image/png'),
        },follow=True)
        self.assertEqual(response.status_code,200)
        meal=content.sections.get(day_number=1,meal_slot='lunch')
        image=meal.media.get(kind='image')
        self.assertIn('orange-lunch',image.uploaded_file.name)
        editor=self.client.get(reverse('treatment_content_manage',args=[content.master_item_id])+'?week_day=1')
        self.assertContains(editor,'حذف عکس ناهار')
        self.assertContains(editor,'orange-lunch')
        remove=self.client.post(reverse('treatment_content_manage',args=[content.master_item_id]),{
            'action':'remove_orange_meal_image','week_day':'1','week_slot':'lunch',
            'week_body':'ناهار: مرغ و سالاد',
        },follow=True)
        self.assertEqual(remove.status_code,200)
        self.assertFalse(meal.media.filter(kind='image').exists())
        meal.refresh_from_db()
        self.assertEqual(meal.body,'ناهار: مرغ و سالاد')
        self.assertEqual(TreatmentRichContent.objects.count(),5)

    def test_reject_wrong_zip_atomically(self):
        self.client.force_login(self.admin)
        response=self.client.post(reverse('treatment_content_library'),{
            'archive':SimpleUploadedFile('wrong.zip',b'not a zip',content_type='application/zip'),
        },follow=True)
        self.assertEqual(response.status_code,200)
        self.assertEqual(TreatmentRichContent.objects.count(),0)

    def test_doctor_selector_keeps_master_title_and_preview_link(self):
        self._upload()
        from core.doctor_views import _catalog_options
        options=_catalog_options('diet',self.branch,())
        keto=next(x for x in options if x['name']=='Keto-Fast')
        self.assertIsNotNone(keto['preview_id'])
