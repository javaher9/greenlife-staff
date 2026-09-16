from django.test import SimpleTestCase

from core import lead_management_views


class LeadHubPaidSalesSourceTests(SimpleTestCase):
    def test_successful_leads_include_approved_referral_sales(self):
        source = open(lead_management_views.__file__, encoding='utf-8').read()
        self.assertIn("status__in=('approved', 'paid')", source)
        self.assertIn("Q(status='won') | Q(pk__in=paid_ids)", source)
        self.assertIn("successful_ids=_successful_lead_ids(leads)", source)
        self.assertIn("op_success_ids=_successful_lead_ids(qs)", source)
