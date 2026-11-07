from datetime import datetime
from unittest.mock import patch
from urllib.parse import urlencode

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import resolve, reverse
from django.utils import timezone

from core.call_center_identity import FlowerLeadProxy
from core.instagram_views import instagram_ads_lead
from core.lead_management_views import _channel_q
from core.lead_routing import _pending_channel, _pending_destination, release_pending_leads_if_ready
from core.models import Attendance, EmployeeProfile, ReferralLead, StaffNotification


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
        self.assertEqual(_pending_destination(lead), ('اینستاگرام - لینک', 'لید جدید تبلیغات'))
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


class InstagramAdsEndToEndTests(TestCase):
    """All writes are confined to Django's disposable local test database."""

    def setUp(self):
        self.clock = patch('django.utils.timezone.now', return_value=timezone.make_aware(
            datetime(2026, 11, 7, 12), timezone.get_current_timezone(),
        ))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.url = reverse('instagram_ads_lead')
        self.payload = {
            'full_name': 'آزمون تبلیغات', 'phone': '09121234001',
            'interested_service': 'درخواست مشاوره', 'consent': 'on',
        }
        user = User.objects.create_user(username='ads-babayi', first_name='فاطمه', last_name='بابایی')
        self.operator = user.profile
        self.operator.role = 'call_center'
        self.operator.save(update_fields=['role'])
        Attendance.objects.create(user=user, date=timezone.localdate(), check_in=timezone.now(), status='present')
        self.manager = User.objects.create_user(username='ads-hub-manager')
        self.manager.profile.role = 'internal_manager'
        self.manager.profile.save(update_fields=['role'])

    def test_ad_requires_explicit_unchecked_consent_and_rejects_direct_post(self):
        page = self.client.get(self.url)
        self.assertContains(page, 'name="consent"')
        self.assertFalse(page.context['form']['consent'].value())
        self.assertTrue(page.context['form'].fields['consent'].required)
        for value in (None, '', 'false'):
            with self.subTest(value=value):
                payload = dict(self.payload)
                if value is None:
                    payload.pop('consent')
                else:
                    payload['consent'] = value
                response = self.client.post(self.url, payload)
                self.assertIn('consent', response.context['form'].errors)
                self.assertFalse(response.context['completed'])
                self.assertFalse(ReferralLead.objects.exists())
                self.assertFalse(StaffNotification.objects.exists())

    def test_tagged_ad_reaches_actual_operator_and_management_views(self):
        url = self.url + '?' + urlencode({'ad_page': 'https://www.instagram.com/beauty.page/'})
        response = self.client.post(url, self.payload)
        self.assertContains(response, 'درخواست شما ثبت شد')
        lead = ReferralLead.objects.get(phone=self.payload['phone'])
        self.assertEqual(lead.assigned_to_id, self.operator.pk)
        self.assertIsNotNone(lead.assigned_at)
        self.assertEqual(lead.group.name, 'اینستاگرام')
        self.assertEqual(lead.source, 'link')
        self.assertIn('[ad_page:beauty.page]', lead.notes)
        self.assertIn('[consent:contact_v1]', lead.notes)
        self.assertIn('[consent_at:', lead.notes)
        self.assertIn('ad_page=', lead.source_url)
        self.assertTrue(StaffNotification.objects.filter(user=self.operator.user, title='لید جدید تبلیغات').exists())
        self.client.force_login(self.operator.user)
        queue = self.client.get(reverse('call_center_dashboard'))
        self.assertContains(queue, 'تبلیغات · @beauty.page')
        self.assertContains(queue, f'data-lead-id="{lead.pk}"')
        self.client.force_login(self.manager)
        hub = self.client.get(reverse('lead_management_dashboard'), {'source': 'advertising'})
        self.assertContains(hub, 'تبلیغات · @beauty.page')
        self.assertContains(hub, lead.full_name)
        self.assertEqual([x.pk for x in hub.context['recent_leads']], [lead.pk])
        trend = self.client.get(reverse('lead_management_trend_data'), {'source': 'advertising'})
        self.assertEqual(trend.status_code, 200)
        self.assertEqual(sum(row['leads'] for row in trend.json()['series']), 1)
        organic_trend = self.client.get(reverse('lead_management_trend_data'), {'source': 'instagram'})
        self.assertEqual(sum(row['leads'] for row in organic_trend.json()['series']), 0)
        organic = self.client.get(reverse('lead_management_dashboard'), {'source': 'instagram'})
        self.assertNotContains(organic, f'data-lead-row="{lead.pk}"')

    def test_night_ad_waits_then_releases_to_same_instagram_group(self):
        night = timezone.make_aware(datetime(2026, 11, 7, 23), timezone.get_current_timezone())
        with patch('django.utils.timezone.now', return_value=night):
            self.client.post(self.url + '?ad_page=night.page', self.payload)
            lead = ReferralLead.objects.get(phone=self.payload['phone'])
            self.assertIsNone(lead.assigned_to_id)
            self.assertIsNone(lead.assigned_at)
            self.assertEqual(_pending_channel(lead), 'instagram')
        next_day = timezone.make_aware(datetime(2026, 11, 8, 12), timezone.get_current_timezone())
        with patch('django.utils.timezone.now', return_value=next_day):
            Attendance.objects.filter(user=self.operator.user).update(
                date=timezone.localdate(), check_in=timezone.now(),
            )
            self.assertEqual(release_pending_leads_if_ready(), 1)
        lead.refresh_from_db()
        self.assertEqual(lead.assigned_to_id, self.operator.pk)
        self.assertEqual(lead.group.name, 'اینستاگرام')
        self.assertEqual(FlowerLeadProxy(lead).source_page_display, 'تبلیغات · @night.page')

    def test_duplicate_and_invalid_phone_do_not_create_extra_leads(self):
        self.client.post(self.url, self.payload)
        duplicate = self.client.post(self.url, self.payload)
        self.assertIn('phone', duplicate.context['form'].errors)
        invalid = self.client.post(self.url, dict(self.payload, phone='123'))
        self.assertIn('phone', invalid.context['form'].errors)
        self.assertEqual(ReferralLead.objects.count(), 1)
        self.assertEqual(StaffNotification.objects.filter(title='لید جدید تبلیغات').count(), 1)

    def test_source_classification_matches_ui_sql_and_pending_routing(self):
        self.client.post(self.url, self.payload)
        lead = ReferralLead.objects.get(phone=self.payload['phone'])
        cases = (
            ('https://app.greenlifeclinics.com/instagram/ads/', '', True),
            ('https://staff.greenlifeclinics.com/instagram/fast/?utm_medium=paid', '', True),
            ('https://app.greenlifeclinics.com/instagram/?utm_source=ig&utm_medium=paid_story', '', True),
            ('https://app.greenlifeclinics.com/instagram/?utm_medium=PAID_SOCIAL&x=1', '', True),
            ('https://app.greenlifeclinics.com/instagram/?utm_medium=paid_story_extra', '', False),
            ('https://app.greenlifeclinics.com/website/?utm_medium=paid_social', '', False),
            ('https://app.greenlifeclinics.com/instagram/?next=/instagram/ads/', '', False),
            ('', '[ENTRY:ADVERTISING]', True),
        )
        for url, notes, expected in cases:
            with self.subTest(url=url, notes=notes):
                ReferralLead.objects.filter(pk=lead.pk).update(source_url=url, notes=notes)
                lead.refresh_from_db()
                self.assertEqual(FlowerLeadProxy(lead)._is_paid_advertising(), expected)
                self.assertEqual(ReferralLead.objects.filter(pk=lead.pk).filter(_channel_q('advertising')).exists(), expected)
                if expected:
                    self.assertEqual(_pending_channel(lead), 'instagram')
                    self.assertEqual(_pending_destination(lead), ('اینستاگرام - لینک', 'لید جدید تبلیغات'))
                    self.assertFalse(ReferralLead.objects.filter(pk=lead.pk).filter(_channel_q('instagram')).exists())

    def test_csrf_roundtrip_on_each_public_domain(self):
        for index, host in enumerate(('app.greenlifeclinics.com', 'staff.greenlifeclinics.com')):
            with self.subTest(host=host):
                client = Client(enforce_csrf_checks=True)
                client.get(self.url, secure=True, HTTP_HOST=host)
                payload = dict(self.payload, phone=f'0912123410{index}')
                blocked = client.post(self.url, payload, secure=True, HTTP_HOST=host, HTTP_ORIGIN=f'https://{host}')
                self.assertEqual(blocked.status_code, 403)
                self.assertFalse(ReferralLead.objects.filter(phone=payload['phone']).exists())
                token = client.cookies['csrftoken'].value
                response = client.post(self.url, dict(payload, csrfmiddlewaretoken=token), secure=True,
                                       HTTP_HOST=host, HTTP_ORIGIN=f'https://{host}')
                self.assertContains(response, 'درخواست شما ثبت شد')
                lead = ReferralLead.objects.get(phone=payload['phone'])
                self.assertTrue(lead.source_url.startswith(f'https://{host}/instagram/ads/'))

    def test_link_builder_always_uses_app_domain(self):
        url = reverse('instagram_ads_link_builder')
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.manager)
        for host in ('app.greenlifeclinics.com', 'staff.greenlifeclinics.com'):
            page = self.client.get(url, secure=True, HTTP_HOST=host)
            self.assertEqual(page.context['ads_base_url'], 'https://app.greenlifeclinics.com/instagram/ads/')
