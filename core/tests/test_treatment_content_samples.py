"""Regression for safe five-item MHTML import and rich-content doctor preview."""
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

IMG=base64.b64decode(
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScLttAAAAABJRU5ErkJggg=='
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
        self.client.force_login(self.doctor)
        self.assertEqual(self.client.get(reverse('treatment_content_preview',args=[content.master_item_id])).status_code,404)

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
