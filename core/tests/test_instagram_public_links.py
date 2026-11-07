"""Contract tests for the shared visual and independent organic/paid intake.

Never redirect staff-only manual registration or token-gated operator entry.
"""
from django.test import TestCase
from django.urls import resolve, reverse


class InstagramPublicLinksTests(TestCase):
    def test_organic_links_keep_their_url_and_source(self):
        for legacy in ('instagram_lead', 'instagram_fast_lead'):
            with self.subTest(legacy=legacy):
                response = self.client.get(reverse(legacy), {
                    'source': 'drjavaherian',
                    'utm_source': 'instagram',
                    'utm_medium': 'paid_story',
                    'utm_campaign': 'november',
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context['instagram_page'], 'Drjavaherian')
                self.assertNotIn('Location', response)

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
        self.assertContains(response, 'name="consent"')

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
