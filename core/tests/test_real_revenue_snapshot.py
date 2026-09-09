from datetime import date

from django.test import SimpleTestCase

from core.templatetags.finance_intelligence import _clinic_revenue_snapshot


class RealClinicRevenueSnapshotTests(SimpleTestCase):
    def test_current_jalali_month_totals_match_real_json_snapshot(self):
        snapshot = _clinic_revenue_snapshot(date(2026, 9, 9))

        self.assertTrue(snapshot['available'])
        self.assertEqual(snapshot['record_count'], 43)
        self.assertEqual(snapshot['grand_total'], 3_947_000_000)
        self.assertEqual(snapshot['grand_total_display'], '3947')

        totals = {row['name']: row['total'] for row in snapshot['branches']}
        self.assertEqual(totals['نیاوران'], 2_725_000_000)
        self.assertEqual(totals['پونک'], 794_000_000)
        self.assertEqual(totals['اصفهان'], 426_000_000)
        self.assertEqual(totals['ارومیه'], 2_000_000)
        displays = {row['name']: row['total_display'] for row in snapshot['branches']}
        self.assertEqual(displays['نیاوران'], '2725')
        self.assertEqual(displays['پونک'], '794')
        self.assertEqual(displays['اصفهان'], '426')
        self.assertEqual(displays['ارومیه'], '2')

    def test_missing_branch_day_is_not_converted_to_zero(self):
        snapshot = _clinic_revenue_snapshot(date(2026, 9, 9))
        sep_second = next(row for row in snapshot['timeline'] if row['date'] == '2026-09-02')

        self.assertEqual(sep_second['values']['نیاوران'], 35_000_000)
        self.assertEqual(sep_second['values']['اصفهان'], 6_000_000)
        self.assertNotIn('پونک', sep_second['values'])
