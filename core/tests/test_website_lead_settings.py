import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.credential_security import decrypt_secret, encrypt_secret
from core.models import ReferralLead, WebsiteLeadIntegrationSettings


class WebsiteLeadIntegrationSettingsTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('website-admin','admin@example.com','x')

    def test_admin_can_generate_key(self):
        self.client.force_login(self.admin)
        response=self.client.post(reverse('website_lead_settings'),{'action':'rotate'})
        self.assertEqual(response.status_code,302)
        config=WebsiteLeadIntegrationSettings.load()
        self.assertTrue(config.is_enabled)
        self.assertTrue(config.api_key_cipher)
        self.assertGreater(len(decrypt_secret(config.api_key_cipher)),20)

    def test_database_key_authorizes_ingest(self):
        config=WebsiteLeadIntegrationSettings.load()
        config.api_key_cipher=encrypt_secret('db-website-key')
        config.is_enabled=True
        config.save()
        response=self.client.post(
            reverse('lead_ingest'),
            data=json.dumps({'name':'Website Test','mobile':'09121234567','source':'website'}),
            content_type='application/json',
            HTTP_X_LEAD_TOKEN='db-website-key',
        )
        self.assertEqual(response.status_code,201)
        self.assertEqual(ReferralLead.objects.count(),1)

    def test_disabled_database_key_cannot_be_used(self):
        config=WebsiteLeadIntegrationSettings.load()
        config.api_key_cipher=encrypt_secret('db-website-key')
        config.is_enabled=False
        config.save()
        response=self.client.post(
            reverse('lead_ingest'),
            data=json.dumps({'name':'Website Test','mobile':'09121234567','source':'website'}),
            content_type='application/json',
            HTTP_X_LEAD_TOKEN='db-website-key',
        )
        self.assertEqual(response.status_code,401)
        self.assertEqual(ReferralLead.objects.count(),0)
