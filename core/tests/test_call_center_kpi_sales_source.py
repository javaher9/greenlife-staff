from pathlib import Path
from django.test import SimpleTestCase


class CallCenterKpiSalesSourceGuardTests(SimpleTestCase):
    def test_dashboard_has_financial_attribution_support(self):
        apps=(Path(__file__).resolve().parents[1]/'apps.py').read_text(encoding='utf-8')
        self.assertIn('finance_attribution',apps)
