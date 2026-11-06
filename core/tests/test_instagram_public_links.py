"""Contract tests for one public Instagram lead landing page.

Never redirect staff-only manual registration or token-gated operator entry.
"""
from urllib.parse import parse_qs, urlsplit

from django.test import SimpleTestCase
from django.urls import resolve, reverse


class InstagramPublicLinksTests(SimpleTestCase):
    def test_old_public_links_redirect_to_the_same_ads_form(self):
        canonical = reverse('instagram_ads_lead')
        for legacy in ('instagram_lead', 'instagram_fast_lead'):
            with self.subTest(legacy=legacy):
                response = self.client.get(reverse(legacy), {
                    'source': 'drjavaherian',
                    'utm_source': 'instagram',
                    'utm_medium': 'paid_story',
                    'utm_campaign': 'november',
                })
                self.assertEqual(response.status_code, 302)
                target = urlsplit(response['Location'])
                self.assertEqual(target.path, canonical)
                params = parse_qs(target.query)
                self.assertEqual(params['source'], ['drjavaherian'])
                self.assertEqual(params['utm_source'], ['instagram'])
                self.assertEqual(params['utm_medium'], ['paid_story'])
                self.assertEqual(params['utm_campaign'], ['november'])

    def test_old_public_post_is_handled_without_302_data_loss(self):
        for legacy in ('instagram_lead', 'instagram_fast_lead'):
            with self.subTest(legacy=legacy):
                response = self.client.post(reverse(legacy), {})
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, 'advertising-page')
                self.assertContains(response, 'name="interested_service"')
                self.assertNotContains(response, 'name="consent"')

    def test_ads_url_shows_approved_form(self):
        response = self.client.get(reverse('instagram_ads_lead'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'مشاوره تخصصی')
        self.assertContains(response, 'لاغری هوشمند')
        self.assertContains(response, 'name="interested_service"')
        self.assertNotContains(response, 'name="consent"')

    def test_internal_instagram_routes_stay_independent(self):
        self.assertEqual(resolve('/instagram/manual/').url_name, 'instagram_manual_lead')
        self.assertEqual(
            resolve('/instagram/entry/laleh/testtoken/').url_name,
            'instagram_operator_quick_lead',
        )
        self.assertEqual(
            resolve('/api/instagram/webhook/').url_name,
            'instagram_webhook',
        )
