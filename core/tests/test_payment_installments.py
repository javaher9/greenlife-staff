from datetime import time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.jalali import format_jalali
from core.models import (
    Branch, ConsultationPlan, ConsultationPlanItem, EmployeeProfile,
    FinancialTransaction, VisitAppointment,
)


class ConsultationInstallmentTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='پرداخت اقساطی تست')
        self.receptionist=User.objects.create_user('reception-deposit',password='pass')
        EmployeeProfile.objects.update_or_create(
            user=self.receptionist,defaults={'branch':self.branch,'role':'receptionist'},
        )
        self.visit=VisitAppointment.objects.create(
            branch=self.branch,full_name='بیمار اقساطی',phone='09121112233',
            appointment_date=timezone.localdate(),appointment_time=time(11,0),
            status='arrived',care_stage='payment',source='receptionist',
            created_by=self.receptionist,
        )
        self.plan=ConsultationPlan.objects.create(
            appointment=self.visit,consultant=self.receptionist,
            status='payment_pending',final_amount_toman=Decimal('10000000'),
            subtotal_toman=Decimal('10000000'),
        )
        ConsultationPlanItem.objects.create(
            plan=self.plan,kind='device',title='Cryo70',quantity=5,
            unit_price_toman=Decimal('2000000'),
        )
        self.client.force_login(self.receptionist)

    def pay(self,amount,token):
        return self.client.post(reverse('finance_entry'),{
            'date':format_jalali(timezone.localdate()),
            'entry_type':'inc',
            'appointment':str(self.visit.pk),
            'person_name':self.visit.full_name,
            'amount':str(amount),
            'sale_reason':'device_package',
            'sale_origin':'afsariyeh',
            'payment_method':'Cash',
            'cash_currency':'IRR',
            'cash_amount':str(amount),
            'service':'Cryo70 × 5',
            'account_heading':'Cryo70',
            'terminal_or_payee':'پذیرش',
            'description':'بیعانه و تسویه',
            'submission_token':token,
        })

    def test_deposit_then_settlement_do_not_duplicate_or_close_early(self):
        first=self.pay(20000000,'aa111111111111111111111111111111')
        self.assertEqual(first.status_code,302)
        self.plan.refresh_from_db()
        self.visit.refresh_from_db()
        self.assertEqual(self.plan.status,'partial_paid')
        self.assertEqual(self.visit.care_stage,'payment')
        initial=self.client.get(
            reverse('finance_entry'),{'appointment':self.visit.pk},
        )
        self.assertEqual(initial.status_code,200)
        self.assertEqual(initial.context['form'].initial['amount'],Decimal('80000000'))
        second=self.pay(80000000,'bb111111111111111111111111111111')
        self.assertEqual(second.status_code,302)
        self.plan.refresh_from_db()
        self.visit.refresh_from_db()
        self.assertEqual(self.plan.status,'paid')
        self.assertEqual(self.visit.care_stage,'closed')
        self.assertEqual(
            FinancialTransaction.objects.filter(appointment=self.visit).count(),2,
        )

    def test_payment_above_remaining_is_rejected(self):
        self.assertEqual(self.pay(20000000,'cc111111111111111111111111111111').status_code,302)
        self.assertEqual(self.pay(90000000,'dd111111111111111111111111111111').status_code,302)
        self.assertEqual(
            FinancialTransaction.objects.filter(appointment=self.visit).count(),1,
        )
        self.plan.refresh_from_db()
        self.assertEqual(self.plan.status,'partial_paid')
