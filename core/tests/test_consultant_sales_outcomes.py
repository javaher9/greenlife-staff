from datetime import time, timedelta
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from core.models import Branch, EmployeeProfile, ReferralLead, ReferralProfile, ReferralSale, Task, VisitAppointment


class ConsultantSalesOutcomeTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Outcome Test')
        self.consultant_user = User.objects.create_user('consultant-outcome', password='pass')
        self.consultant = EmployeeProfile.objects.create(user=self.consultant_user, branch=self.branch, role='consultant')
        self.operator_user = User.objects.create_user('operator-outcome', password='pass')
        self.operator = EmployeeProfile.objects.create(user=self.operator_user, branch=self.branch, role='call_center')
        source_user = User.objects.create_user('source-outcome', password='pass')
        self.source = ReferralProfile.objects.create(user=source_user, referral_code='OUTCOME1')
        self.lead = ReferralLead.objects.create(referrer=self.source, full_name='مراجع تست', phone='09120000000', status='visited', assigned_to=self.operator, first_appointment_by=self.operator_user)
        self.appointment = VisitAppointment.objects.create(lead=self.lead, branch=self.branch, full_name=self.lead.full_name, phone=self.lead.phone, appointment_date=timezone.localdate(), appointment_time=time(10, 0), status='arrived', source='call_center', created_by=self.operator_user)
        self.client.force_login(self.consultant_user)

    def test_success_creates_approved_sale_and_wins_lead(self):
        response = self.client.post(reverse('consultant_sales_outcomes'), {'appointment_id': self.appointment.pk, 'result': 'success', 'sale_type': 'device', 'amount_toman': '2000000', 'note': 'تست'})
        self.assertEqual(response.status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'won')
        sale = ReferralSale.objects.get(lead=self.lead)
        self.assertEqual(sale.amount, 2000000)
        self.assertEqual(sale.status, 'approved')
        self.assertEqual(sale.recorded_by, self.consultant_user)
        self.assertIn('پکیج دستگاه', sale.note)

    def test_failed_routes_followup_to_operator_for_tomorrow(self):
        response = self.client.post(reverse('consultant_sales_outcomes'), {'appointment_id': self.appointment.pk, 'result': 'failed', 'failure_reason': 'financial', 'note': ''})
        self.assertEqual(response.status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'contacted')
        self.assertEqual(self.lead.next_follow_up, timezone.localdate() + timedelta(days=1))
        task = Task.objects.get(assigned_to=self.operator_user)
        self.assertEqual(task.due_date, timezone.localdate() + timedelta(days=1))
        self.assertIn('مشکل مالی', task.description)

    def test_other_failure_requires_note(self):
        response = self.client.post(reverse('consultant_sales_outcomes'), {'appointment_id': self.appointment.pk, 'result': 'failed', 'failure_reason': 'other', 'note': ''})
        self.assertEqual(response.status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'visited')
        self.assertFalse(Task.objects.filter(assigned_to=self.operator_user).exists())
