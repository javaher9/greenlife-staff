from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.lead_freshness_views import _monitor_window
from core.models import EmployeeProfile, ReferralLead, ReferralProfile


class LastLeadPulseTests(TestCase):
    def aware(self, day, hour, minute=0):
        return datetime(2026, 11, day, hour, minute, tzinfo=ZoneInfo('Asia/Tehran'))

    def test_window_crosses_midnight_without_alerts_at_night(self):
        for day, hour, active in [(5, 7, False), (5, 8, True), (5, 23, True), (6, 0, True), (6, 1, False)]:
            self.assertEqual(_monitor_window(self.aware(day, hour))[0], active)

    def setUp(self):
        self.manager=User.objects.create_user('pulse-manager')
        EmployeeProfile.objects.update_or_create(user=self.manager,defaults={'role':'internal_manager','is_active':True})
        self.other=User.objects.create_user('pulse-employee')
        EmployeeProfile.objects.update_or_create(user=self.other,defaults={'role':'employee','is_active':True})
        self.referrer=ReferralProfile.objects.create(user=User.objects.create_user('pulse-source'),referral_code='PULSE123')

    def test_access_and_warning_after_sixty_minutes(self):
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('live_last_lead')).status_code,403)
        self.client.force_login(self.manager)
        with patch('core.lead_freshness_views.timezone.now',return_value=self.aware(5,9,1)):
            data=self.client.get(reverse('live_last_lead')).json()
        self.assertTrue(data['alert'])
        self.assertEqual(data['threshold_minutes'],60)
        self.assertIsNone(data['last_lead_at'])

    def test_new_lead_clears_warning_and_off_hours_suppress_warning(self):
        lead=ReferralLead.objects.create(referrer=self.referrer,full_name='تست ضربان لید',phone='09123334455')
        ReferralLead.objects.filter(pk=lead.pk).update(created_at=self.aware(5,9,30))
        self.client.force_login(self.manager)
        with patch('core.lead_freshness_views.timezone.now',return_value=self.aware(5,9,59)):
            data=self.client.get(reverse('live_last_lead')).json()
        self.assertFalse(data['alert'])
        self.assertLess(data['elapsed_seconds'],3600)
        with patch('core.lead_freshness_views.timezone.now',return_value=self.aware(6,2)):
            data=self.client.get(reverse('live_last_lead')).json()
        self.assertFalse(data['monitoring'])
        self.assertFalse(data['alert'])
