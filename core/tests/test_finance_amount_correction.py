from pathlib import Path

from django.test import SimpleTestCase


class FinanceAmountCorrectionWiringTests(SimpleTestCase):
    def test_amount_correction_is_audited_and_installed(self):
        root = Path(__file__).resolve().parents[2]
        module = (root / 'core' / 'finance_amount_correction.py').read_text(encoding='utf-8')
        apps = (root / 'core' / 'apps.py').read_text(encoding='utf-8')
        template = (root / 'core' / 'templates' / 'core' / 'finance_amount_correction.html').read_text(encoding='utf-8')
        self.assertIn("action='finance_amount_correction'", module)
        self.assertIn("'old_amount': str(old_amount)", module)
        self.assertIn("'new_amount': str(new_amount)", module)
        self.assertIn("entry.amount = new_amount", module)
        self.assertIn('install_finance_amount_correction()', apps)
        self.assertIn('name=\"corrected_amount\"', template)
        self.assertIn('مبلغ قبلی برای سابقه حسابرسی نگهداری می‌شود', template)
