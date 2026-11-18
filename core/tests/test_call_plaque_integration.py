import json
import uuid
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.call_plaque import empty_data
from core.models import EmployeeProfile, LeadCallProfile, ReferralLead, ReferralProfile


class CallPlaqueIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator = User.objects.create_user('plaque-integration-operator')
        cls.admin = User.objects.create_user('plaque-integration-admin')
        EmployeeProfile.objects.update_or_create(user=cls.operator, defaults={'role': 'call_center', 'is_active': True})
        EmployeeProfile.objects.update_or_create(user=cls.admin, defaults={'role': 'admin', 'is_active': True})
        referrer = ReferralProfile.objects.create(user=cls.admin, referral_code='PLAQUE-INTEGRATION')
        cls.lead = ReferralLead.objects.create(referrer=referrer, full_name='پرونده آزمون پلاک', phone='09123456780', assigned_to=cls.operator.profile)

    def setUp(self):
        self.client.force_login(self.operator)
        self.url = reverse('call_center_call_plaque', args=[self.lead.pk])

    def test_dashboard_and_detail_open_own_plaque(self):
        for url in (reverse('call_center_dashboard'), reverse('call_center_lead', args=[self.lead.pk])):
            response = self.client.get(url)
            self.assertContains(response, 'data-call-plaque-url="' + self.url + '"')
            self.assertContains(response, 'id="glCallPlaque"', count=1)
            self.assertContains(response, 'اطلاعات ناکافی')
            self.assertContains(response, 'data-cp-operator-only')
            self.assertContains(response, 'data-cp-prior-title')
            self.assertContains(response, 'call-plaque.js?v=20261118-2')

    def test_scheduled_followup_opens_same_plaque(self):
        ReferralLead.objects.filter(pk=self.lead.pk).update(next_follow_up=timezone.localdate() + timedelta(days=2), contact_result='follow_up')
        response = self.client.get(reverse('call_center_follow_up_agenda'), {'tab': 'future'})
        self.assertContains(response, 'data-call-plaque-url="' + self.url + '"')
        self.assertContains(response, 'id="glCallPlaque"', count=1)

    def test_completed_call_visible_from_admin_compact_lead(self):
        data = empty_data()
        data['outcome'] = 'answered'
        data['answers']['goal'] = {'state': 'answered', 'value': 'آشنایی با خدمات'}
        data['answers']['priority'] = {'state': 'answered', 'value': 'اطمینان از روش'}
        data['communication_style'] = 'details'
        data['communication_evidence'] = 'خودش توضیح مرحله‌ای خواست'
        saved = self.client.post(self.url, json.dumps({'version': 0, 'request_id': str(uuid.uuid4()), 'action': 'finalize', 'data': data}), content_type='application/json')
        self.assertEqual(saved.status_code, 200, saved.content)
        self.client.force_login(self.admin)
        items = self.client.get(reverse('management_all_leads_data')).json()['items']
        item = next(row for row in items if row['id'] == self.lead.pk)
        self.assertEqual(item['plaque_url'], self.url)
        self.assertEqual(item['readiness']['score'], saved.json()['profile']['readiness']['score'])
        self.assertNotIn('phone', item)
        history = self.client.get(item['plaque_url']).json()
        self.assertFalse(history['editable'])
        self.assertEqual(history['history_total'], 1)
        self.assertEqual(history['profile']['communication_style'], 'details')
        self.assertEqual(history['history'][0]['data']['answers']['priority']['value'], 'اطمینان از روش')

    def test_old_detail_form_cannot_reschedule_opted_out_lead(self):
        LeadCallProfile.objects.create(lead=self.lead, do_not_contact=True)
        original = ReferralLead.objects.get(pk=self.lead.pk)
        response = self.client.post(reverse('call_center_lead', args=[self.lead.pk]), {'contact_result': 'follow_up', 'notes': 'must not save'})
        self.assertEqual(response.status_code, 200)
        current = ReferralLead.objects.get(pk=self.lead.pk)
        self.assertEqual(current.notes, original.notes)
        self.assertEqual(current.contact_result, original.contact_result)
        self.assertEqual(current.next_follow_up, original.next_follow_up)
