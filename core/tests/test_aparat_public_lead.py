from django.test import TestCase
from django.urls import reverse

from core.call_center_identity import FlowerLeadProxy
from core.models import ReferralLead


class AparatPublicLeadTests(TestCase):
    def test_aparat_page_is_available(self):
        response=self.client.get(reverse('aparat_public_lead'))
        self.assertEqual(response.status_code,200)
        body=response.content.decode('utf-8')
        self.assertIn('مشاوره رایگان لاغری',body)
        self.assertIn('شماره موبایل',body)

    def test_aparat_submission_is_labeled_aparat(self):
        response=self.client.post(reverse('aparat_public_lead'),{
            'full_name':'تست آپارات',
            'phone':'09121234567',
            'notes':'چربی موضعی شکم و پهلو',
        })
        self.assertEqual(response.status_code,200)
        lead=ReferralLead.objects.get(full_name='تست آپارات')
        self.assertIn('/aparat/',lead.source_url)
        self.assertEqual(FlowerLeadProxy(lead).source_page_display,'آپارات')
