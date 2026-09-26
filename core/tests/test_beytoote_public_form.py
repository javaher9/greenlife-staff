from django.test import TestCase
from django.urls import reverse

from core.models import ReferralLead


class BeytootePublicLeadPageTests(TestCase):
    def test_page_is_simplified_and_campaign_styled(self):
        response=self.client.get(reverse('beytoote_public_lead'))
        self.assertEqual(response.status_code,200)
        body=response.content.decode('utf-8')
        self.assertIn('rf-beytoote',body)
        self.assertIn('نام و نام خانوادگی',body)
        self.assertIn('شماره موبایل',body)
        self.assertIn('چربی موضعی شما بیشتر در کدام ناحیه است؟',body)
        self.assertNotIn('شماره جایگزین',body)
        self.assertNotIn('خدمت موردنظر',body)
        self.assertNotIn('اجازه می‌دهم کارشناسان',body)

    def test_beytoote_submission_is_saved_with_beytoote_source_url(self):
        response=self.client.post(reverse('beytoote_public_lead'),{
            'full_name':'تست بیتوته',
            'phone':'09121234567',
            'notes':'چربی موضعی شکم و پهلو',
        })
        self.assertEqual(response.status_code,200)
        lead=ReferralLead.objects.get(full_name='تست بیتوته')
        self.assertEqual(lead.source,'link')
        self.assertIn('/beytoote/',lead.source_url)
        self.assertIsNone(lead.assigned_to)
