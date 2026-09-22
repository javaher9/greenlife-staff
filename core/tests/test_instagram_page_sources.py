from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Attendance, Branch, EmployeeProfile, ReferralLead


class InstagramPageSourceTests(TestCase):
    def setUp(self):
        branch = Branch.objects.create(name='کال‌سنتر')
        operator_user = User.objects.create_user(username='ig-page-operator', password='x')
        self.operator, _ = EmployeeProfile.objects.update_or_create(
            user=operator_user,
            defaults={'role': 'call_center', 'branch': branch, 'is_active': True},
        )
        Attendance.objects.create(
            user=operator_user, branch=branch, date=timezone.localdate(),
            check_in=timezone.now(), status='present',
        )
        self.staff = User.objects.create_user(username='ig-page-staff', password='x')
        manager_user = User.objects.create_user(username='ig-page-manager', password='x')
        self.manager, _ = EmployeeProfile.objects.update_or_create(
            user=manager_user,
            defaults={'role': 'manager', 'branch': branch, 'is_active': True},
        )

    def _public_payload(self):
        return {
            'full_name': 'مراجع منبع اینستاگرام',
            'phone': '09121234567',
            'interested_service': 'لاغری',
            'consent': 'on',
        }

    def test_story_link_records_exact_instagram_page(self):
        response = self.client.post(
            reverse('instagram_lead') + '?source=greenlife_cafe',
            self._public_payload(),
        )
        self.assertEqual(response.status_code, 200)
        lead = ReferralLead.objects.get(full_name='مراجع منبع اینستاگرام')
        self.assertIn('پیج: Greenlife.cafe', lead.notes)
        self.assertIn('[instagram_page:greenlife_cafe]', lead.notes)
        self.assertIn('source=greenlife_cafe', lead.source_url)

    def test_unknown_public_source_falls_back_to_greenlifeclinics(self):
        payload = self._public_payload()
        payload['phone'] = '09121234568'
        response = self.client.post(
            reverse('instagram_lead') + '?source=unknown-page',
            payload,
        )
        self.assertEqual(response.status_code, 200)
        lead = ReferralLead.objects.get(phone='09121234568')
        self.assertIn('پیج: Greenlifeclinics', lead.notes)
        self.assertIn('[instagram_page:greenlifeclinics]', lead.notes)

    def test_manual_form_defaults_to_greenlifeclinics_and_can_change_page(self):
        self.client.force_login(self.staff)
        page = self.client.get(reverse('instagram_manual_lead'))
        self.assertEqual(page.status_code, 200)
        self.assertContains(
            page,
            '<option value="greenlifeclinics" selected>Greenlifeclinics</option>',
            html=True,
        )

        response = self.client.post(reverse('instagram_manual_lead'), {
            'full_name': 'دایرکت دکتر',
            'phone': '09121234569',
            'interested_service': 'مشاوره',
            'instagram_page': 'drjavaherian',
        })
        self.assertEqual(response.status_code, 200)
        lead = ReferralLead.objects.get(phone='09121234569')
        self.assertEqual(lead.source, 'panel')
        self.assertIn('پیج: Drjavaherian', lead.notes)
        self.assertIn('[instagram_page:drjavaherian]', lead.notes)


    def test_origin_is_visible_to_call_center_and_management_statistics(self):
        response = self.client.post(
            reverse('instagram_lead') + '?source=greenlife_cafe',
            self._public_payload(),
        )
        self.assertEqual(response.status_code, 200)

        self.client.force_login(self.operator.user)
        dashboard = self.client.get(reverse('call_center_dashboard'))
        self.assertEqual(dashboard.status_code, 200)
        self.assertContains(dashboard, 'اینستاگرام · لینک · Greenlife.cafe')

        self.client.force_login(self.manager.user)
        hub = self.client.get(reverse('lead_management_dashboard'))
        self.assertEqual(hub.status_code, 200)
        self.assertContains(hub, 'آمار پیج‌های اینستاگرام')
        self.assertContains(hub, 'Greenlife.cafe')
        self.assertContains(hub, 'Greenlife.cafe')
        self.assertContains(hub, '<th>گروه</th><th>منبع</th><th>وضعیت</th>')
