from collections import Counter
from datetime import datetime, time

from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone

from core.lead_routing import assign_external_lead, assign_referral_lead, release_pending_leads_if_ready
from core.models import Attendance, EmployeeProfile, ReferralLead, ReferralProfile


class UnifiedLeadRoutingTests(TestCase):
    def setUp(self):
        source_user = User.objects.create_user(username='routing-source', password='x')
        self.source = ReferralProfile.objects.create(
            user=source_user,
            referral_code='GLROUTETEST',
            is_active=True,
        )
        self.operators = []
        for first_name, last_name, username in (
            ('فاطمه', 'بابایی', 'babayi-routing'),
            ('محمد', 'صالحی', 'salehi-routing'),
            ('حدیث', 'توانا', 'tavana-routing'),
            ('پریسا', 'کلکلی', 'kolkoli-routing'),
            ('زهرا', 'آزادی', 'azadi-routing'),
            ('شیما', 'عباسی', 'abbasi-routing'),
        ):
            user = User.objects.create_user(
                username=username,
                first_name=first_name,
                last_name=last_name,
                password='x',
                is_active=True,
            )
            profile = user.profile
            profile.role = 'call_center'
            profile.is_active = True
            profile.save(update_fields=['role', 'is_active'])
            self.operators.append(profile)

    def _new_lead(self, index):
        return ReferralLead.objects.create(
            referrer=self.source,
            full_name=f'لید {index}',
            phone=f'0912000{index:04d}',
            status='new',
            source='panel',
        )

    def _check_in(self, *operator_indexes):
        now = timezone.now()
        today = timezone.localdate()
        for index in operator_indexes:
            Attendance.objects.update_or_create(
                user=self.operators[index].user,
                date=today,
                defaults={'check_in': now, 'check_out': None, 'status': 'present'},
            )

    def _keep_only(self, *operator_indexes):
        keep = set(operator_indexes)
        for index, operator in enumerate(self.operators):
            if index not in keep:
                operator.is_active = False
                operator.save(update_fields=['is_active'])

    def _at(self, hour, minute=0):
        naive = datetime.combine(timezone.localdate(), time(hour, minute))
        return timezone.make_aware(naive, timezone.get_current_timezone())

    def test_lead_waits_when_nobody_is_present(self):
        lead = self._new_lead(1)
        self.assertIsNone(assign_referral_lead(lead))
        lead.refresh_from_db()
        self.assertIsNone(lead.assigned_to_id)
        self.assertIsNone(lead.assigned_at)

    def test_equal_distribution_when_team_is_present(self):
        self._check_in(*range(6))
        assigned = []
        for index in range(1, 13):
            lead = self._new_lead(index)
            assigned.append(assign_referral_lead(lead).id)

        counts = Counter(assigned)
        self.assertEqual(
            [counts[operator.id] for operator in self.operators],
            [2, 2, 2, 2, 2, 2],
        )

    def test_late_operator_catches_up_instead_of_first_arrival_keeping_all_leads(self):
        self._keep_only(0, 1)
        self._check_in(0)

        for index in range(1, 5):
            lead = self._new_lead(index)
            self.assertEqual(assign_referral_lead(lead).id, self.operators[0].id)

        self._check_in(1)
        for index in range(5, 9):
            lead = self._new_lead(index)
            self.assertEqual(assign_referral_lead(lead).id, self.operators[1].id)

        counts = Counter(
            ReferralLead.objects.values_list('assigned_to_id', flat=True)
        )
        self.assertEqual(counts[self.operators[0].id], 4)
        self.assertEqual(counts[self.operators[1].id], 4)

    def test_overnight_backlog_waits_for_more_staff_before_11(self):
        self._keep_only(0, 1)
        leads = [self._new_lead(index) for index in range(1, 7)]
        self._check_in(0)

        released = release_pending_leads_if_ready(now=self._at(9, 30))
        self.assertEqual(released, 0)
        self.assertEqual(
            ReferralLead.objects.filter(assigned_to__isnull=True).count(),
            6,
        )

        self._check_in(1)
        released = release_pending_leads_if_ready(now=self._at(10, 0))
        self.assertEqual(released, 6)

        counts = Counter(
            ReferralLead.objects.values_list('assigned_to_id', flat=True)
        )
        self.assertEqual(counts[self.operators[0].id], 3)
        self.assertEqual(counts[self.operators[1].id], 3)
        for lead in leads:
            lead.refresh_from_db()
            self.assertIsNotNone(lead.assigned_at)

    def test_website_leads_never_go_to_kamelya_or_laleh(self):
        self._check_in(*range(6))
        assigned=[]
        for index in range(20, 32):
            lead=ReferralLead.objects.create(
                referrer=self.source,
                full_name=f'وب‌سایت {index}',
                phone=f'0913000{index:04d}',
                status='new',
                source='link',
                source_url='https://greenlifeclinics.com/start/',
                notes='[channel:website]',
            )
            operator=assign_external_lead(lead,'website')
            self.assertIsNotNone(operator)
            assigned.append(operator.id)

        blocked={self.operators[3].id,self.operators[5].id}
        self.assertTrue(blocked.isdisjoint(set(assigned)))
        allowed={self.operators[i].id for i in (0,1,2,4)}
        self.assertTrue(set(assigned).issubset(allowed))

    def test_website_lead_waits_if_only_kamelya_and_laleh_are_present(self):
        self._keep_only(3,5)
        self._check_in(3,5)
        lead=ReferralLead.objects.create(
            referrer=self.source,
            full_name='وب‌سایت مهم',
            phone='09139999991',
            status='new',
            source='link',
            source_url='https://greenlifeclinics.com/',
            notes='[channel:website]',
        )

        self.assertIsNone(assign_external_lead(lead,'website'))
        lead.refresh_from_db()
        self.assertIsNone(lead.assigned_to_id)

    def test_pending_website_leads_also_skip_kamelya_and_laleh(self):
        self._check_in(*range(6))
        leads=[]
        for index in range(40,46):
            leads.append(ReferralLead.objects.create(
                referrer=self.source,
                full_name=f'وب‌سایت صف {index}',
                phone=f'0914000{index:04d}',
                status='new',
                source='link',
                source_url='https://greenlifeclinics.com/landing/',
                notes='[channel:website]',
            ))

        released=release_pending_leads_if_ready(force=True)
        self.assertEqual(released,6)
        blocked={self.operators[3].id,self.operators[5].id}
        for lead in leads:
            lead.refresh_from_db()
            self.assertIsNotNone(lead.assigned_to_id)
            self.assertNotIn(lead.assigned_to_id,blocked)

    def test_inactive_operator_is_never_selected(self):
        self.operators[3].is_active = False
        self.operators[3].save(update_fields=['is_active'])
        self._check_in(0, 1, 2, 4, 5)

        assigned = []
        for index in range(1, 11):
            lead = self._new_lead(index)
            assigned.append(assign_referral_lead(lead).id)

        self.assertNotIn(self.operators[3].id, assigned)
