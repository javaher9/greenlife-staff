from datetime import time
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Branch, EmployeeProfile, VisitAppointment


class IntakeLinkTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='نیاوران')
        self.user = User.objects.create_user(
            username='intake-receptionist',
            password='test-password',
        )
        EmployeeProfile.objects.update_or_create(
            user=self.user,
            defaults={
                'role': 'receptionist',
                'branch': self.branch,
                'is_active': True,
            },
        )
        self.appointment = VisitAppointment.objects.create(
            branch=self.branch,
            full_name='بیمار تست',
            phone='09120000000',
            service='آنالیز',
            appointment_date=timezone.localdate(),
            appointment_time=time(10, 0),
            status='arrived',
            source='receptionist',
            created_by=self.user,
        )
        self.client.force_login(self.user)

    @override_settings(PUBLIC_BASE_URL='https://staff.greenlifeclinics.com')
    @patch('intake.views.send_sms')
    def test_send_link_uses_configured_public_base_url(self, mocked_send_sms):
        response = self.client.post(
            reverse('intake_send_link', args=[self.appointment.pk]),
        )

        self.assertRedirects(response, reverse('appointment_schedule'))
        message = mocked_send_sms.call_args.args[1]
        self.assertIn(
            'https://staff.greenlifeclinics.com/intake/form/',
            message,
        )
        self.assertNotIn('app.greenlifeclinics.com', message)

