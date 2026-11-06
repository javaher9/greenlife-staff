from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import resolve, reverse

from core.call_center_identity import FlowerLeadProxy
from core.instagram_views import instagram_ads_lead
from core.lead_management_views import _channel_q
from core.lead_routing import _pending_destination
from core.models import EmployeeProfile, ReferralLead


class PaidInstagramAdsTests(TestCase):
    def setUp(self):
        self.manager = User.objects.create_user(username='paid-ad-manager')
        EmployeeProfile.objects.update_or_create(
            user=self.manager, defaults={'role': 'internal_manager', 'is_active': True},
        )

    def test_short_link_is_public_and_tracks_paid_source(self):
        url = reverse('instagram_ads_lead')
        self.assertEqual(url, '/instagram/ads/')
        self.assertIs(resolve(url).func, instagram_ads_lead)
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {
            'full_name': 'مراجع تست تبلیغات',
            'phone': '09124567890',
            'interested_service': 'لاغری موضعی',
            'consent': 'on',
        })
        self.assertEqual(response.status_code, 200)
        lead = ReferralLead.objects.get(phone='09124567890')
        self.assertIn('[entry:advertising]', lead.notes)
        self.assertIn('منبع: تبلیغات', lead.notes)
        self.assertIn('/instagram/ads/', lead.source_url)
        self.assertEqual(FlowerLeadProxy(lead).source_page_display, 'تبلیغات')
        self.assertEqual(FlowerLeadProxy(lead).source_origin_display, 'تبلیغات')
        self.assertEqual(_pending_destination(lead), ('کمپ', 'لید جدید تبلیغات'))
        self.assertEqual(ReferralLead.objects.filter(_channel_q('advertising')).count(), 1)
        self.assertEqual(ReferralLead.objects.filter(_channel_q('instagram')).count(), 0)

    def test_paid_ad_is_separately_filterable_in_management(self):
        self.client.post(reverse('instagram_ads_lead'), {
            'full_name': 'ورودی تبلیغات',
            'phone': '09124567891',
            'consent': 'on',
        })
        self.client.force_login(self.manager)
        response = self.client.get(reverse('lead_management_dashboard'), {'source': 'advertising'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'ورودی تبلیغات')
        self.assertContains(response, 'تبلیغات')
        self.assertEqual(response.context['source_filter'], 'advertising')
