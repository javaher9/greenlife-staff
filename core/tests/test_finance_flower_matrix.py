from datetime import time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import RequestFactory, TestCase
from django.utils import timezone

from core.models import (
    Branch, EmployeeProfile, FinancialTransaction, ReferralLead,
    ReferralProfile, VisitAppointment,
)
from core.templatetags.finance_intelligence import finance_intelligence


class FinanceFlowerMatrixTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='نیاوران')
        self.second_branch = Branch.objects.create(name='پونک')
        self.admin = self._user('finance-admin', 'مدیر', 'سیستم', 'admin')
        self.flower = self._user('m-salehi', 'محمد', 'صالحی', 'call_center')
        self.other_flower = self._user('h-tavana', 'حدیث', 'توانا', 'call_center')

    def _user(self, username, first, last, role):
        user = User.objects.create_user(
            username=username, first_name=first, last_name=last,
            password='test-password',
        )
        EmployeeProfile.objects.update_or_create(
            user=user, defaults={'role': role, 'is_active': True},
        )
        return user

    def _income(self, amount, *, owner=None, appointment=None, branch=None,
                status='approved', reason='device_package'):
        return FinancialTransaction.objects.create(
            source='manual', branch=branch or self.branch,
            occurred_at=timezone.now(), amount=Decimal(str(amount)),
            entry_type='inc', review_status=status, sale_reason=reason,
            person_name='مراجع تست', call_center_owner=owner,
            appointment=appointment,
        )

    def _report(self, **filters):
        request = RequestFactory().get('/finance/', {'period': 'today', **filters})
        request.user = self.admin
        return finance_intelligence({'request': request, 'selected': timezone.localdate()})

    def _appointment(self):
        referrer_user = self._user('ref-source', 'معرف', 'تست', 'referrer')
        referrer = ReferralProfile.objects.create(
            user=referrer_user, referral_code='FINMATRIX-TEST',
        )
        lead = ReferralLead.objects.create(
            referrer=referrer, full_name='مراجع نوبت',
            phone='09120009999', first_appointment_by=self.flower,
        )
        return VisitAppointment.objects.create(
            lead=lead, branch=self.branch,
            full_name=lead.full_name, phone=lead.phone,
            appointment_date=timezone.localdate(), appointment_time=time(10, 0),
            source='call_center', created_by=self.flower,
        )

    def test_aliases_in_filter_matrix_and_finance_ledger(self):
        self._income('200000000', owner=self.flower)
        self.client.force_login(self.admin)
        response = self.client.get('/finance/')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'گل خورشیدی')
        self.assertContains(response, 'گل بنفشه')
        self.assertNotContains(response, 'گل محمد صالحی')
        self.assertNotContains(response, 'گل حدیث توانا')
        report = self._report()
        rows = {r['flower'].user_id: r for r in report['matrix_rows']}
        self.assertEqual(rows[self.flower.pk]['total'], Decimal('200000000'))

    def test_unowned_direct_sales_are_visible_not_falsely_credited(self):
        manual = self._income('596000000')
        self._income('60000000', status='pending')
        report = self._report()
        self.assertEqual(report['total'], Decimal('596000000'))
        self.assertEqual(report['matrix_attributed_total'], Decimal('0'))
        self.assertEqual(report['matrix_unassigned_total'], Decimal('596000000'))
        self.assertEqual(report['matrix_reconciled_total'], report['total'])
        self.assertEqual(report['matrix_total_cells'][0]['total'], report['total'])
        manual.refresh_from_db()
        self.assertIsNone(manual.call_center_owner_id)
        self.client.force_login(self.admin)
        response = self.client.get('/finance/')
        self.assertContains(response, 'بدون انتساب معتبر به گل')
        self.assertContains(response, 'جمع درآمد تأییدشده')
        self.assertContains(response, '596')

    def test_first_booking_owner_fills_display_only_and_flower_filter(self):
        appointment = self._appointment()
        legacy_receipt = self._income('140000000', appointment=appointment)
        self._income('50000000', owner=self.other_flower, branch=self.second_branch)
        report = self._report()
        rows = {r['flower'].user_id: r for r in report['matrix_rows']}
        self.assertEqual(rows[self.flower.pk]['total'], Decimal('140000000'))
        self.assertEqual(rows[self.other_flower.pk]['total'], Decimal('50000000'))
        self.assertEqual(report['matrix_unassigned_total'], Decimal('0'))
        self.assertEqual(report['matrix_reconciled_total'], report['total'])
        selected = self._report(flower=str(self.flower.pk))
        self.assertEqual(selected['total'], Decimal('140000000'))
        self.assertEqual(selected['matrix_reconciled_total'], selected['total'])
        self.assertEqual(selected['matrix_unassigned_total'], Decimal('0'))
        legacy_receipt.refresh_from_db()
        self.assertIsNone(legacy_receipt.call_center_owner_id)

    def test_inactive_historical_flower_is_not_silently_dropped(self):
        self._income('70000000', owner=self.flower)
        self.flower.profile.is_active = False
        self.flower.profile.save(update_fields=['is_active'])
        report = self._report()
        row = next(r for r in report['matrix_rows'] if r['flower'].user_id == self.flower.pk)
        self.assertTrue(row['historical'])
        self.assertEqual(row['total'], Decimal('70000000'))
        self.assertEqual(report['matrix_reconciled_total'], report['total'])

    def test_branch_service_filters_preserve_reconciliation(self):
        self._income('90000000', owner=self.flower, branch=self.branch)
        self._income('120000000', branch=self.second_branch)
        self._income('30000000', reason='lipolytic', branch=self.branch)
        report = self._report(branch=str(self.branch.pk), service='device_package')
        self.assertEqual(report['total'], Decimal('90000000'))
        self.assertEqual(report['matrix_reconciled_total'], report['total'])
        self.assertEqual(report['matrix_unassigned_total'], Decimal('0'))
        self.assertEqual(len(report['matrix_branches']), 1)
