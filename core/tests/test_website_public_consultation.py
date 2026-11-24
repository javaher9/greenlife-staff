"""Public consultation contract; all submissions use Django's isolated test DB."""
from urllib.parse import urlencode
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse

from core.models import ReferralLead


class WebsitePublicConsultationTests(TestCase):
    def setUp(self):
        self.url = reverse('website_public_lead')

    def test_existing_url_renders_accessible_new_form_without_creating_a_lead(self):
        response = self.client.get(self.url)
        self.assertTemplateUsed(response, 'core/website_lead.html')
        self.assertContains(response, 'ما شما را لاغر می‌کنیم')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'type="tel"')
        self.assertContains(response, 'href="https://greenlifeclinics.com/"')
        self.assertNotContains(response, 'name="consent"')
        self.assertNotContains(response, 'class="consultation-details" open')
        self.assertFalse(ReferralLead.objects.exists())

    def test_invalid_submission_preserves_details_and_does_not_create_a_lead(self):
        response = self.client.post(self.url, {
            'full_name': 'آزمون محلی', 'phone': '۱۲۳',
            'interested_service': 'توضیح باقی بماند',
        })
        self.assertContains(response, 'شماره موبایل معتبر وارد کنید.')
        self.assertContains(response, 'class="consultation-details" open')
        self.assertContains(response, 'توضیح باقی بماند')
        self.assertContains(response, 'aria-invalid="true"')
        self.assertFalse(ReferralLead.objects.exists())

    def test_valid_submission_keeps_attribution_normalization_routing_and_duplicate_protection(self):
        page = 'https://greenlifeclinics.com/device-slimming/?area=arm'
        url = self.url + '?' + urlencode({'page': page, 'cta': 'مشاوره بازو'})
        data = {'full_name': 'آزمون محلی', 'phone': '+۹۸۹۱۲۱۲۳۴۵۶۷', 'interested_service': 'مشاوره'}
        with patch('core.website_public_lead_views._assign_lead') as assign:
            response = self.client.post(url, data)
        lead = ReferralLead.objects.get()
        self.assertEqual(lead.phone, '09121234567')
        self.assertEqual(lead.source_url, page)
        self.assertIn('مشاوره بازو', lead.notes)
        self.assertEqual(lead.interested_service, 'مشاوره')
        assign.assert_called_once_with(lead, 'website')
        self.assertContains(response, 'درخواست شما ثبت شد')
        self.assertNotContains(response, 'id="websiteLeadForm"')
        repeat = self.client.post(url, data)
        self.assertEqual(ReferralLead.objects.count(), 1)
        self.assertTrue(repeat.context['form'].errors.get('phone'))

    def test_csrf_still_required(self):
        response = Client(enforce_csrf_checks=True).post(self.url, {
            'full_name': 'آزمون محلی', 'phone': '09121234567',
        })
        self.assertEqual(response.status_code, 403)
        self.assertFalse(ReferralLead.objects.exists())

    def test_other_public_form_keeps_its_existing_template(self):
        response = self.client.get(reverse('telegram_lead'))
        self.assertTemplateUsed(response, 'core/instagram_lead.html')
        self.assertNotContains(response, 'ghazal-niavaran-v1')
