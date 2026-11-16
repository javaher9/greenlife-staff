"""CC G correction option must coexist with one (not two) CC S choice."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import AuditLog, Branch, EmployeeProfile, FinancialTransaction


class FinanceCorrectionCompanyCardTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='نیاوران')
        self.admin=User.objects.create_user(username='ccg-correction-admin',password='test')
        EmployeeProfile.objects.update_or_create(
            user=self.admin,defaults={'role':'admin','branch':self.branch,'is_active':True},
        )
        self.entry=FinancialTransaction.objects.create(
            source='manual',entry_type='inc',
            branch=self.branch,occurred_at=timezone.now(),
            person_name='مراجع مالی',amount=Decimal('110000000'),
            payment_method='CC S',sale_origin='branch_walk_in',
            sale_reason='device_package',review_status='pending',
        )
        self.client.force_login(self.admin)
        self.url=reverse('finance_entry_review',args=[self.entry.pk,'correction'])

    def test_correction_selector_contains_one_ccs_and_one_ccg(self):
        response=self.client.post(self.url,{'corrected_amount':''})
        self.assertEqual(response.status_code,200)
        html=response.content.decode('utf-8')
        self.assertEqual(html.count('<option value="CC S"'),1)
        self.assertEqual(html.count('<option value="CC G"'),1)
        self.assertIn('<option value="CC S" selected',html)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.payment_method,'CC S')
        self.assertEqual(self.entry.review_status,'pending')

    def test_ccg_correction_changes_original_only_and_is_audited(self):
        payload={
            'corrected_amount':'11',
            'entry_type':'inc',
            'payment_method':'CC G',
            'sale_origin':'branch_walk_in',
            'sale_reason':'device_package',
            'branch_id':str(self.branch.pk),
            'person_name':'مراجع مالی',
            'service':'پکیج دستگاه',
            'account_heading':'خدمات',
            'terminal_or_payee':'حساب شرکت',
            'tracking_number':'CCG-2026-11',
            'destination_card':'',
            'description':'اصلاح مقصد دریافت',
            'review_note':'اصلاح به کارت‌به‌کارت شرکت',
        }
        response=self.client.post(self.url,payload)
        self.assertRedirects(response,reverse('finance_dashboard'),fetch_redirect_response=False)
        self.assertEqual(FinancialTransaction.objects.count(),1)
        self.entry.refresh_from_db()
        self.assertEqual(self.entry.amount,Decimal('110000000'))
        self.assertEqual(self.entry.payment_method,'CC G')
        self.assertEqual(self.entry.review_status,'approved')
        audit=AuditLog.objects.get(action='finance_transaction_correction')
        self.assertEqual(audit.metadata['changes']['payment_method']['before'],'CC S')
        self.assertEqual(audit.metadata['changes']['payment_method']['after'],'CC G')
