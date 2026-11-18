from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from core.agent_flow import daily_flow
from core.customer_portal_models import CustomerPortalMember, CustomerServiceRequest
from core.me_sync_models import MeSyncAudit
from core.models import Branch, CallCenterLeadGroup, ReferralLead, ReferralProfile


class FlowCounterTests(TestCase):
    def test_shared_registration_and_visit_are_separate_from_leads(self):
        member = CustomerPortalMember.objects.create(
            phone='09120000001', referral_code='atlas-member', last_login_at=timezone.now(),
        )
        branch = Branch.objects.create(name='آزمایشی')
        CustomerServiceRequest.objects.create(member=member, branch=branch, kind='visit')
        CustomerServiceRequest.objects.create(member=member, branch=branch, kind='diet')
        MeSyncAudit.objects.create(member=member, version=1, action='sync')
        counts = daily_flow(timezone.localtime())['counts']
        self.assertEqual([counts[k] for k in ('account', 'sync', 'request', 'booked')], [1, 1, 1, 0])
        self.assertEqual(counts.get('crm', 0), 0)
        self.assertNotIn(member.phone, str(counts))

    def test_sources_partition_today_and_count_assignments(self):
        source = ReferralProfile.objects.create(user=get_user_model().objects.create_user('test-flow'), referral_code='flow')
        group, _ = CallCenterLeadGroup.objects.get_or_create(name='وب سایت')
        first = ReferralLead.objects.create(referrer=source, group=group, phone='09120000002', full_name='A')
        ReferralLead.objects.create(referrer=source, phone='09120000003', full_name='B')
        counts = daily_flow(timezone.localtime())['counts']
        self.assertEqual([counts[k] for k in ('website', 'other', 'crm', 'assigned')], [1, 1, 2, 0])
        ReferralLead.objects.filter(pk=first.pk).update(created_at=timezone.now()-timedelta(days=1))
        counts = daily_flow(timezone.localtime())['counts']
        self.assertEqual(counts.get('website', 0), 0)
        self.assertEqual(counts['crm'], 1)
