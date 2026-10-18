from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Attendance, Branch, CallCenterLeadGroup, EmployeeProfile, ReferralLead
from core.lead_routing import _pending_destination


class TelegramLeadTests(TestCase):
    def setUp(self):
        call_branch = Branch.objects.create(name='کال‌سنتر')
        user = User.objects.create_user(username='telegram-operator', password='x')
        self.operator, _ = EmployeeProfile.objects.update_or_create(
            user=user,
            defaults={'role': 'call_center', 'branch': call_branch, 'is_active': True},
        )
        Attendance.objects.create(
            user=user, branch=call_branch, date=timezone.localdate(),
            check_in=timezone.now(), status='present',
        )

    def test_public_telegram_form_creates_lead_in_telegram_group(self):
        response = self.client.post(reverse('telegram_lead'), {
            'full_name': 'مراجع تلگرام',
            'phone': '09121234567',
            'interested_service': 'لاغری',
            'consent': 'on',
        })
        self.assertEqual(response.status_code, 200)
        lead = ReferralLead.objects.get(full_name='مراجع تلگرام')
        self.assertEqual(lead.phone, '09121234567')
        # Leads created before the daily release stay pending; ownership is not invented.
        if lead.assigned_to_id:
            self.assertEqual(lead.assigned_to, self.operator)
            self.assertEqual(lead.group.name, 'تلگرام - لینک')
        else:
            self.assertEqual(_pending_destination(lead)[0], 'تلگرام - لینک')
        self.assertEqual(lead.source, 'link')
        self.assertIn('/telegram/', lead.source_url)
        self.assertIn('تلگرام', lead.notes)
        if lead.group_id:
            self.assertTrue(
                CallCenterLeadGroup.objects.filter(owner__isnull=True, name='تلگرام - لینک').exists()
            )
