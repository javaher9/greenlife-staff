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
        self.consultant = EmployeeProfile.objects.update_or_create(user=self.consultant_user, defaults={'branch':self.branch, 'role':'consultant'})[0]
        self.operator_user = User.objects.create_user('operator-outcome', password='pass')
        self.operator = EmployeeProfile.objects.update_or_create(user=self.operator_user, defaults={'branch':self.branch, 'role':'call_center'})[0]
        source_user = User.objects.create_user('source-outcome', password='pass')
        self.source = ReferralProfile.objects.create(user=source_user, referral_code='OUTCOME1')
        self.lead = ReferralLead.objects.create(referrer=self.source, full_name='مراجع تست', phone='09120000000', status='visited', assigned_to=self.operator, first_appointment_by=self.operator_user)
        self.appointment = VisitAppointment.objects.create(lead=self.lead, branch=self.branch, full_name=self.lead.full_name, phone=self.lead.phone, appointment_date=timezone.localdate(), appointment_time=time(10, 0), status='arrived', care_stage='consultant', source='call_center', created_by=self.operator_user)
        self.client.force_login(self.consultant_user)

    def test_legacy_success_does_not_bypass_finance_approval(self):
        response=self.client.post(reverse('consultant_sales_outcomes'), {'appointment_id':self.appointment.pk,'result':'success','amount_toman':'2000000'})
        self.assertEqual(response.status_code,302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status,'visited')
        self.assertFalse(ReferralSale.objects.filter(lead=self.lead).exists())

    def test_failed_routes_followup_to_operator_for_tomorrow(self):
        response = self.client.post(reverse('consultant_sales_outcomes'), {'appointment_id': self.appointment.pk, 'action': 'no_sale', 'failure_reason': 'financial', 'note': ''})
        self.assertEqual(response.status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'contacted')
        self.assertEqual(self.lead.next_follow_up, timezone.localdate() + timedelta(days=1))
        task = Task.objects.get(assigned_to=self.operator_user)
        self.assertEqual(task.due_date, timezone.localdate() + timedelta(days=1))
        self.assertIn('مشکل مالی', task.description)

    def test_other_failure_records_followup(self):
        response = self.client.post(reverse('consultant_sales_outcomes'), {'appointment_id': self.appointment.pk, 'action': 'no_sale', 'failure_reason': 'other', 'note': ''})
        self.assertEqual(response.status_code, 302)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'contacted')
        self.assertTrue(Task.objects.filter(assigned_to=self.operator_user).exists())
