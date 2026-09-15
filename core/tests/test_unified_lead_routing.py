from collections import Counter

from django.contrib.auth.models import User
from django.test import TestCase

from core.lead_routing import assign_referral_lead
from core.models import EmployeeProfile, ReferralLead, ReferralProfile


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
            self.operators.append(EmployeeProfile.objects.create(
                user=user,
                role='call_center',
                is_active=True,
            ))

    def _new_lead(self, index):
        return ReferralLead.objects.create(
            referrer=self.source,
            full_name=f'لید {index}',
            phone=f'0912000{index:04d}',
            status='new',
            source='panel',
        )

    def test_first_pass_is_rotational_not_five_to_one_operator(self):
        assigned = []
        for index in range(1, 7):
            lead = self._new_lead(index)
            assigned.append(assign_referral_lead(lead).id)
        self.assertEqual(len(set(assigned)), 6)

    def test_twenty_leads_match_requested_weights(self):
        assigned = []
        for index in range(1, 21):
            lead = self._new_lead(index)
            assigned.append(assign_referral_lead(lead).id)

        counts = Counter(assigned)
        expected = [6, 4, 3, 3, 3, 1]
        self.assertEqual([counts[operator.id] for operator in self.operators], expected)

    def test_inactive_operator_is_never_selected(self):
        self.operators[3].is_active = False
        self.operators[3].save(update_fields=['is_active'])

        assigned = []
        for index in range(1, 10):
            lead = self._new_lead(index)
            assigned.append(assign_referral_lead(lead).id)

        self.assertNotIn(self.operators[3].id, assigned)
