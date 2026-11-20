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

    def test_journey_uses_the_same_lead_for_owner_and_booking_even_across_midnight(self):
        from core.models import EmployeeProfile, VisitAppointment

        users = get_user_model().objects
        source = ReferralProfile.objects.create(user=users.create_user('lead-source-telegram'), referral_code='tg')
        operator, _ = EmployeeProfile.objects.update_or_create(user=users.create_user('babayi'), defaults={'role':'call_center'})
        lead = ReferralLead.objects.create(
            referrer=source, assigned_to=operator, assigned_at=timezone.now(),
            phone='09120000008', full_name='Private name',
        )
        now = timezone.localtime()
        ReferralLead.objects.filter(pk=lead.pk).update(created_at=now-timedelta(days=1))
        unrelated = VisitAppointment.objects.create(
            branch=Branch.objects.create(name='نمونه'), phone=lead.phone, full_name=lead.full_name,
            appointment_date=now.date(), appointment_time='12:00',
        )
        flow = daily_flow(timezone.localtime())
        row, = flow['journeys']
        self.assertEqual((row['source'], row['owner'], row['booked']), ('تلگرام', 'نرگس', None))
        self.assertNotIn(lead.full_name, str(flow))
        self.assertNotIn(lead.phone, str(flow))
        unrelated.lead = lead
        unrelated.save(update_fields=['lead'])
        self.assertTrue(daily_flow(timezone.localtime())['journeys'][0]['booked'])
        unrelated.status = 'cancelled'
        unrelated.save(update_fields=['status'])
        row, = daily_flow(timezone.localtime())['journeys']
        self.assertIsNone(row['booked'])
        self.assertTrue(row['cancelled'])

    def test_receipt_only_does_not_create_a_journey_or_an_assignment(self):
        from core.models import ChannelMessageReceipt
        ChannelMessageReceipt.objects.create(provider='bale', bot_id=1, update_id=1)
        self.assertEqual(daily_flow(timezone.localtime())['journeys'], [])
        source = ReferralProfile.objects.create(user=get_user_model().objects.create_user('observer'), referral_code='observer')
        lead = ReferralLead.objects.create(referrer=source, full_name='P', phone='09120000009', status='appointment')
        row, = daily_flow(timezone.localtime())['journeys']
        self.assertEqual((row['id'], row['owner'], row['source'], row['booked']), (lead.pk, '', 'منبع ثبت نشده', None))
