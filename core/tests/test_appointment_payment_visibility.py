from datetime import time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Branch,
    EmployeeProfile,
    FinancialTransaction,
    ReferralLead,
    ReferralProfile,
    VisitAppointment,
)
from core.templatetags.jalali_tags import appointment_paid_million


class AppointmentPaymentVisibilityTests(TestCase):
    def setUp(self):
        self.call_branch = Branch.objects.create(name='کال‌سنتر')
        self.branch = Branch.objects.create(name='نیاوران')
        self.operator = self._user('payment-operator', 'call_center', self.call_branch, 'نرگس')
        self.receptionist = self._user('payment-receptionist', 'receptionist', self.branch, 'منشی')
        referrer_user = self._user('payment-referrer', 'employee', self.branch, 'معرف')
        self.referrer = ReferralProfile.objects.create(
            user=referrer_user,
            referral_code='GLPAYMENTFLOW',
            created_by=referrer_user,
        )
        self.lead = ReferralLead.objects.create(
            referrer=self.referrer,
            full_name='مراجع چرخه کامل',
            phone='09120008888',
            interested_service='لاغری',
            assigned_to=self.operator.profile,
            status='appointment',
        )
        self.appointment = VisitAppointment.objects.create(
            lead=self.lead,
            branch=self.branch,
            full_name=self.lead.full_name,
            phone=self.lead.phone,
            service='لاغری',
            appointment_date=timezone.localdate(),
            appointment_time=time(10, 0),
            source='call_center',
            created_by=self.operator,
        )

    @staticmethod
    def _user(username, role, branch, first_name):
        user = User.objects.create_user(
            username=username,
            password='test-pass',
            first_name=first_name,
        )
        EmployeeProfile.objects.update_or_create(
            user=user,
            defaults={'role': role, 'branch': branch, 'is_active': True},
        )
        return User.objects.get(pk=user.pk)

    def _payment(self, amount, review_status):
        return FinancialTransaction.objects.create(
            source='manual',
            branch=self.branch,
            occurred_at=timezone.now(),
            amount=Decimal(str(amount)),
            entry_type='inc',
            person_name=self.appointment.full_name,
            review_status=review_status,
            recorded_by=self.receptionist,
            appointment=self.appointment,
        )

    def test_only_approved_income_is_shown_as_appointment_payment(self):
        self._payment(20_000_000, 'approved')
        self._payment(30_000_000, 'pending')
        self.assertEqual(appointment_paid_million(self.appointment), '2')

    def test_shared_schedule_shows_approved_payment_to_receptionist_and_call_center(self):
        self._payment(20_000_000, 'approved')
        self._payment(30_000_000, 'pending')
        day = timezone.localdate().isoformat()

        self.client.force_login(self.receptionist)
        receptionist_page = self.client.get(reverse('appointment_schedule'), {'date': day})
        self.assertEqual(receptionist_page.status_code, 200)
        self.assertContains(receptionist_page, 'پرداخت تأییدشده:')
        self.assertContains(receptionist_page, '>2</b> میلیون تومان')

        self.client.force_login(self.operator)
        call_center_page = self.client.get(
            reverse('appointment_schedule'),
            {'date': day, 'branch': self.branch.pk},
        )
        self.assertEqual(call_center_page.status_code, 200)
        self.assertContains(call_center_page, 'پرداخت تأییدشده:')
        self.assertContains(call_center_page, '>2</b> میلیون تومان')

    def test_receptionist_arrival_moves_lead_to_visited_but_never_downgrades_won(self):
        self.client.force_login(self.receptionist)
        response = self.client.post(
            reverse('receptionist_appointment_status', args=[self.appointment.pk, 'arrived'])
        )
        self.assertEqual(response.status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'visited')

        self.lead.status = 'won'
        self.lead.save(update_fields=['status', 'updated_at'])
        response = self.client.post(
            reverse('receptionist_appointment_status', args=[self.appointment.pk, 'completed'])
        )
        self.assertEqual(response.status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'won')
