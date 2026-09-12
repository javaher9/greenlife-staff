import json
import os
from unittest.mock import patch

from django.test import TestCase

from core.models import ReferralLead


class LeadIngestTests(TestCase):
    def _post(self, payload, token='unit-test-token'):
        with patch.dict(os.environ, {'LEAD_INGEST_TOKEN': token}, clear=False):
            return self.client.post(
                '/api/integrations/leads/',
                data=json.dumps(payload),
                content_type='application/json',
                HTTP_X_LEAD_TOKEN=token,
            )

    def test_rejects_unauthorized_request(self):
        response = self.client.post(
            '/api/integrations/leads/',
            data=json.dumps({'name': 'Test', 'mobile': '09121234567'}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code, 401)

    def test_creates_website_lead_with_page_attribution(self):
        response = self._post({
            'name': 'مریم احمدی',
            'mobile': '09121234567',
            'service': 'Double Define',
            'source': 'website',
            'page_url': 'https://greenlifeclinics.com/double-define/?utm_source=instagram&utm_campaign=define',
            'page_title': 'Double Define',
            'form_id': 'consultation-main',
            'landing_page': 'https://greenlifeclinics.com/double-define/',
        })
        self.assertEqual(response.status_code, 201)
        lead = ReferralLead.objects.get()
        self.assertEqual(lead.phone, '09121234567')
        self.assertEqual(lead.source_url, 'https://greenlifeclinics.com/double-define/?utm_source=instagram&utm_campaign=define')
        self.assertIn('[channel:website]', lead.notes)
        self.assertIn('utm_source', lead.notes)
        self.assertIn('instagram', lead.notes)
        self.assertIn('page_title', lead.notes)

    def test_accepts_elementor_style_mobile_field_named_email(self):
        response = self._post({
            'form_id': 'abc123',
            'form_name': 'New Form',
            'name': 'علی رضایی',
            'email': '09120000000',
            'Page URL': 'https://greenlifeclinics.com/fast-slimming/',
            'source': 'website',
        })
        self.assertEqual(response.status_code, 201)
        lead = ReferralLead.objects.get()
        self.assertEqual(lead.phone, '09120000000')
        self.assertEqual(lead.source_url, 'https://greenlifeclinics.com/fast-slimming/')
