from datetime import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.models import Branch, EmployeeProfile, FinancialTransaction, ReferralLead, ReferralProfile, ReferralSale, VisitAppointment


class CallCenterSalesAttributionTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='Attribution Branch')
        self.operator=User.objects.create_user('cc-owner',password='pass')
        EmployeeProfile.objects.update_or_create(user=self.operator,defaults={'role':'call_center','branch':self.branch,'is_active':True})
        source_user=User.objects.create_user('attr-source',password='pass')
        self.referrer=ReferralProfile.objects.create(user=source_user,referral_code='GLATTRTEST',created_by=source_user)
        self.lead=ReferralLead.objects.create(referrer=self.referrer,full_name='مراجع تست',phone='09120009999',assigned_to=self.operator.profile,first_appointment_by=self.operator)
        self.appointment=VisitAppointment.objects.create(lead=self.lead,branch=self.branch,full_name=self.lead.full_name,phone=self.lead.phone,appointment_date=timezone.localdate(),appointment_time=datetime.strptime('10:00','%H:%M').time(),source='call_center',created_by=self.operator,status='arrived')

    def test_approved_appointment_income_becomes_operator_sale(self):
        FinancialTransaction.objects.create(branch=self.branch,appointment=self.appointment,occurred_at=timezone.now(),amount=Decimal('2400000'),entry_type='inc',review_status='approved',call_center_owner=self.operator,source='manual')
        sale=ReferralSale.objects.get(lead=self.lead)
        self.assertEqual(sale.amount,Decimal('2400000'))
        self.assertEqual(sale.status,'approved')
        self.assertEqual(sale.recorded_by,self.operator)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status,'won')

    def test_unapproved_payment_does_not_count_as_sale(self):
        FinancialTransaction.objects.create(branch=self.branch,appointment=self.appointment,occurred_at=timezone.now(),amount=Decimal('900000'),entry_type='inc',review_status='pending',call_center_owner=self.operator,source='manual')
        self.assertFalse(ReferralSale.objects.filter(lead=self.lead).exists())
