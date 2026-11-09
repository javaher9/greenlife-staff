"""Reception dashboard sends intake only through the explicit action."""
from datetime import time
from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import Branch, EmployeeProfile, VisitAppointment
from core.sms import SmsGatewayError
from intake.models import IntakeInvitation

@override_settings(PUBLIC_BASE_URL='https://staff.greenlifeclinics.com')
class ReceptionIntakeActionTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='نیاوران')
        self.user = User.objects.create_user(username='reception-intake-action')
        EmployeeProfile.objects.update_or_create(user=self.user, defaults={
            'role': 'receptionist', 'branch': self.branch, 'is_active': True,
        })
        self.appointment = VisitAppointment.objects.create(
            branch=self.branch, full_name='تست فرم پذیرش', phone='09120000000',
            service='آنالیز', appointment_date=timezone.localdate(),
            appointment_time=time(10), status='booked', source='receptionist',
            created_by=self.user,
        )
        self.client.force_login(self.user)
        self.send_url = reverse('intake_send_link', args=[self.appointment.pk])

    @patch('intake.views.send_sms')
    def test_button_appears_after_reception_and_sends_back_to_dashboard(self, sms):
        before = self.client.get(reverse('dashboard'))
        self.assertEqual(before.status_code, 200)
        self.assertNotContains(before, f'action="{self.send_url}"')
        arrived = self.client.post(
            reverse('receptionist_appointment_status', args=[self.appointment.pk, 'arrived']),
            {'next': 'dashboard'},
        )
        self.assertRedirects(arrived, reverse('dashboard'), fetch_redirect_response=False)
        sms.assert_not_called()
        after = self.client.get(reverse('dashboard'))
        self.assertContains(after, f'action="{self.send_url}"')
        self.assertContains(after, 'ارسال لینک فرم اولیه')
        sent = self.client.post(self.send_url, {'next': 'dashboard', 'resend': '1'})
        self.assertRedirects(sent, reverse('dashboard'), fetch_redirect_response=False)
        sms.assert_called_once()
        self.assertEqual(sms.call_args.args[0], self.appointment.phone)
        self.assertEqual(IntakeInvitation.objects.get(appointment=self.appointment).sms_status, 'accepted')
        self.assertContains(self.client.get(reverse('dashboard')), 'لینک فرم اطلاعات اولیه ارسال شد.')

    @patch('intake.views.send_sms', side_effect=SmsGatewayError('test failure'))
    def test_failed_send_returns_to_dashboard_without_undoing_arrival(self, sms):
        self.appointment.status = 'arrived'
        self.appointment.save()
        response = self.client.post(self.send_url, {'next': 'dashboard'})
        self.assertRedirects(response, reverse('dashboard'), fetch_redirect_response=False)
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status, 'arrived')
        self.assertContains(self.client.get(reverse('dashboard')), 'ارسال پیامک ناموفق بود')

    @patch('intake.views.send_sms')
    def test_schedule_default_return_is_preserved(self, sms):
        self.appointment.status = 'arrived'
        self.appointment.save()
        response = self.client.post(self.send_url)
        self.assertRedirects(response, reverse('appointment_schedule'), fetch_redirect_response=False)

    @patch('intake.views.send_sms')
    def test_unaccepted_appointment_cannot_send(self, sms):
        response = self.client.post(self.send_url, {'next': 'dashboard'})
        self.assertEqual(response.status_code, 404)
        sms.assert_not_called()
