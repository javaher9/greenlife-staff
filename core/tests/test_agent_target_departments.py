from datetime import datetime, timezone as utc_timezone
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse

from core.agent_target_departments import _vessel, target_context
from core.models import Branch, EmployeeProfile, FinancialTransaction, SalesTargetBand, TargetPercentPolicy


@override_settings(EXECUTIVE_USERNAMES=['target-owner'])
class AgentTargetTests(TestCase):
    def test_partial_targets_unknown_amount_zero_and_above_scale(self):
        actual = Decimal("185.25")
        partial = SimpleNamespace(target_one=Decimal(100), target_two=None)
        row = _vessel('flower:2', 'گندم', actual, partial)
        self.assertEqual(row['t1_percent'], Decimal("185.2"))
        self.assertIsNone(row['t2_percent'])
        self.assertEqual(row['level'], 100)
        self.assertEqual(row['reading'], "185.25:100.00:")
        self.assertIn("2", row['availability'])
        partial.target_one, partial.target_two = Decimal(0), Decimal(200)
        row = _vessel('flower:2', 'گندم', Decimal(0), partial)
        self.assertIsNone(row['t1_percent'])
        self.assertIsNone(row['t1_level'])
        self.assertEqual(row['actual_display'], "0")
        self.assertEqual(row['t2_percent'], 0)
        self.assertEqual(row['level'], 0)
        row = _vessel('flower:2', 'گندم', None, partial)
        self.assertIsNone(row['level'])
        self.assertIsNone(row['t2_percent'])
        self.assertIsNotNone(row['t2_level'])
        self.assertIsNone(row['actual_display'])

    def test_tehran_month_policy_and_sources_match_executive_sales_dashboard(self):
        # First minutes of Aban in Tehran, still the previous Gregorian date in UTC.
        now = datetime(2026, 10, 22, 20, 35, tzinfo=utc_timezone.utc)
        branch = Branch.objects.create(name='نیاوران آزمایشی')
        closed = Branch.objects.create(name='شعبه بسته', is_active=False)
        user = get_user_model().objects.create_user(username='target-salehi')
        EmployeeProfile.objects.update_or_create(user=user, defaults={'role':'call_center','is_active':True})
        target_key = f'branch:{branch.pk}'
        SalesTargetBand.objects.create(key=f'1405-08:{target_key}', scope='branch', branch=branch,
            period_year=1405, period_month=8, heavy_limit=2, sales_floor=10, target_one=14, target_two=17)
        TargetPercentPolicy.objects.create(period_year=1405, period_month=8, target_one_percent=150, target_two_percent=200)
        base = dict(amount=Decimal("240000000"), branch=branch, source='manual', entry_type='inc',
                    review_status='approved', call_center_owner=user, occurred_at=now)
        FinancialTransaction.objects.create(**base)
        for excluded in [
            {'occurred_at': now.replace(minute=29)}, {'entry_type':'exp'}, {'source':'crm'}, {'review_status':'pending'},
        ]:
            FinancialTransaction.objects.create(**{**base, **excluded})
        with self.assertNumQueries(6):
            context=target_context(now)
        self.assertEqual(context['target_period'], '1405/08')
        flowers, centers = context['target_departments']
        self.assertFalse(any(row['key'] == f'branch:{closed.pk}' for row in centers['vessels']))
        branch_row = next(row for row in centers['vessels'] if row['key']==target_key)
        self.assertEqual(branch_row['reading'], '24.00:15.00:20.00')
        self.assertEqual(branch_row['level'], 100)
        self.assertEqual(branch_row['t2_percent'], Decimal(120))
        self.assertEqual(branch_row['t1_percent'], Decimal(160))
        flower_row = next(row for row in flowers['vessels'] if row['key']==f'flower:{user.pk}')
        self.assertEqual(flower_row['name'], 'خورشیدی')
        self.assertEqual(flower_row['actual_display'], '24')
        self.assertIsNone(flower_row['level'])
        self.assertIsNone(flower_row['t1_percent'])

        self.client.force_login(get_user_model().objects.create_user(username='target-owner'))
        sales = self.client.get(reverse('sales_targets_dashboard'), {'year':1405, 'month':8}).context
        source_branch = next(row for row in sales['branches'] if row['key']==target_key)
        self.assertEqual(source_branch['plan'].target_two, Decimal('20'))
        self.assertEqual(source_branch['value'], Decimal(branch_row['actual_display']))
        source_flower = next(row for row in sales['flower_cards'] if row['key']==flower_row['key'])
        self.assertEqual(source_flower['value'], Decimal(flower_row['actual_display']))

    def test_periodic_fragment_keeps_same_owner_permission_and_is_opt_in(self):
        url = reverse('agent_activity_snapshot')
        self.assertEqual(self.client.get(url, {'targets':1}).status_code, 302)
        self.client.force_login(get_user_model().objects.create_user(username='target-staff'))
        self.assertEqual(self.client.get(url, {'targets':1}).status_code, 403)
        self.client.force_login(get_user_model().objects.create_user(username='target-owner'))
        self.assertNotIn('target_html', self.client.get(url).json())
        response = self.client.get(url, {'targets':1})
        self.assertIn('no-store', response['Cache-Control'])
        self.assertIn('target_html', response.json())
