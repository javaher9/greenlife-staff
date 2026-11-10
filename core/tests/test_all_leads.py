from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Branch, ConsultationPlan, EmployeeProfile, ReferralLead, ReferralProfile, VisitAppointment


class AllLeadsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('archive-manager')
        EmployeeProfile.objects.update_or_create(user=cls.manager, defaults={'role': 'admin', 'is_active': True})
        cls.worker = User.objects.create_user('tavana')
        cls.flower, _ = EmployeeProfile.objects.update_or_create(user=cls.worker, defaults={'role': 'call_center', 'is_active': True})
        cls.referrer, _ = ReferralProfile.objects.get_or_create(user=cls.manager, defaults={'referral_code': 'archive-tests'})
        cls.branch = Branch.objects.create(name='Archive test branch')
        cls.leads = [ReferralLead.objects.create(referrer=cls.referrer, full_name=f'لید {i}', phone=f'09123450{i:03d}', assigned_to=cls.flower) for i in range(8)]
        # Tied timestamps prove the id tie-breaker, not offset pagination, is used.
        ReferralLead.objects.filter(pk__in=[x.pk for x in cls.leads]).update(created_at=timezone.now()-timedelta(days=250))

    def setUp(self):
        self.client.force_login(self.manager)
        self.url = reverse('management_all_leads_data')

    def appointment(self, lead, status):
        return VisitAppointment.objects.create(lead=lead, branch=self.branch, full_name=lead.full_name, phone=lead.phone, appointment_date=timezone.localdate()+timedelta(days=lead.pk), appointment_time='10:00', status=status)

    def test_auth_and_role_on_page_and_data(self):
        self.client.logout()
        self.assertEqual(self.client.get(self.url).status_code, 302)
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.assertEqual(self.client.get(reverse('management_all_leads')).status_code, 403)

    def test_page_and_real_flower(self):
        page = self.client.get(reverse('management_all_leads'))
        self.assertContains(page, 'همه لیدها')
        self.assertContains(page, 'بنفشه')
        data = self.client.get(self.url).json()
        self.assertEqual(data['total'], 8)
        self.assertTrue(all(x['flower'] == 'بنفشه' and x['label'] == 'جدید' for x in data['items']))
        self.assertNotIn('phone', data['items'][0])

    @patch('core.all_leads_views.PAGE_SIZE', 3)
    def test_cursor_both_directions_ties_and_filter_binding(self):
        for order in ('newest', 'oldest'):
            params = {'sort': order}
            ids = []
            while True:
                data = self.client.get(self.url, params).json()
                ids.extend(x['id'] for x in data['items'])
                if not data['next']:
                    break
                params['cursor'] = data['next']
            self.assertEqual(ids, sorted([x.pk for x in self.leads], reverse=order=='newest'))
        first = self.client.get(self.url).json()
        self.assertEqual(self.client.get(self.url, {'cursor':first['next'], 'q':'changed'}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'cursor':'tampered'}).status_code, 400)

    def test_recorded_outcomes_and_no_inferred_failure(self):
        self.appointment(self.leads[0], 'no_show')
        self.appointment(self.leads[1], 'arrived')
        appt = self.appointment(self.leads[2], 'completed')
        ConsultationPlan.objects.create(appointment=appt, status='paid')
        appt = self.appointment(self.leads[3], 'completed')
        ConsultationPlan.objects.create(appointment=appt, status='no_sale')
        appt = self.appointment(self.leads[4], 'booked')
        ConsultationPlan.objects.create(appointment=appt, status='draft')
        data = {row['id']:row['state'] for row in self.client.get(self.url).json()['items']}
        self.assertEqual([data[x.pk] for x in self.leads[:5]], ['no_show','visited','won','sale_lost','appointment'])
        result = self.client.get(self.url, {'state':'sale_lost'}).json()['items']
        self.assertEqual([x['id'] for x in result], [self.leads[3].pk])

    def test_filters_unknown_branch_date_and_untouched(self):
        self.appointment(self.leads[0], 'booked')
        self.assertEqual(self.client.get(self.url, {'branch':self.branch.pk}).json()['total'], 1)
        self.assertEqual(self.client.get(self.url, {'branch':'none'}).json()['total'], 7)
        self.assertEqual(self.client.get(self.url, {'untouched':'1'}).json()['total'], 7)
        self.assertEqual(self.client.get(self.url, {'q':self.leads[0].full_name}).json()['total'], 1)
        self.assertEqual(self.client.get(self.url, {'from':'not-a-date'}).status_code, 400)
        self.assertEqual(self.client.get(self.url, {'from':'۱۴۰۰/۰۱/۰۱','to':'۱۴۹۹/۱۲/۲۹'}).json()['total'], 8)
        self.assertEqual(self.client.get(self.url, {'flower': self.flower.pk}).json()['total'], 8)

    def test_query_count_does_not_grow_with_page(self):
        from django.test.utils import CaptureQueriesContext
        from django.db import connection
        # CountryWorkspaceMiddleware initializes/saves the session on the first request.
        self.client.get(self.url)
        with CaptureQueriesContext(connection) as many:
            self.client.get(self.url)
        with CaptureQueriesContext(connection) as one:
            self.client.get(self.url, {'q': self.leads[0].full_name})
        self.assertEqual(len(many), len(one))
