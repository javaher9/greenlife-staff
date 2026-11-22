from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.assistant_queue_models import AssistantCallJob
from core.models import AuditLog, LeadCallProfile, LeadCallSession, ReferralLead, ReferralProfile


class AssistantCallQueueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.admin = users.objects.create_user('queue-admin')
        cls.admin.profile.role = 'admin'
        cls.admin.profile.save(update_fields=('role',))
        cls.manager = users.objects.create_user('queue-manager')
        cls.manager.profile.role = 'internal_manager'
        cls.manager.profile.save(update_fields=('role',))
        cls.worker = users.objects.create_user('queue-worker')
        cls.worker.profile.role = 'call_center'
        cls.worker.profile.save(update_fields=('role',))
        cls.referrer, _ = ReferralProfile.objects.get_or_create(
            user=cls.admin, defaults={'referral_code': 'QUEUE-001'},
        )
        cls.due = timezone.localtime(timezone.now() + timedelta(days=2)).replace(microsecond=0)

    def setUp(self):
        self.url = reverse('phone_assistant_queue')
        self.client.force_login(self.admin)

    def _lead(self, suffix=1, *, consent='yes', do_not_contact=False):
        lead = ReferralLead.objects.create(
            referrer=self.referrer, full_name=f'درخواست {suffix}', phone=f'0912000{suffix:04d}',
            contact_result='follow_up', status='contacted', next_follow_up=self.due.date(),
            next_follow_up_time=self.due.time(),
        )
        event = LeadCallSession.objects.create(
            lead=lead, actor=self.worker, state='final', revision=1, data={
                'outcome': 'follow_up', 'followup_consent': consent, 'followup_at': self.due.isoformat(),
                'do_not_contact': do_not_contact,
            },
        )
        LeadCallProfile.objects.create(
            lead=lead, latest_session=event, revision=event.revision, do_not_contact=do_not_contact,
        )
        return lead

    def _post(self, **data):
        return self.client.post(self.url, data, content_type='application/json')

    def test_consent_queue_lifecycle_deduplicates_and_keeps_phone_private(self):
        lead = self._lead()
        self._lead(2, consent='unknown')
        self._lead(3, do_not_contact=True)
        initial = self.client.get(self.url)
        self.assertEqual(initial.status_code, 200)
        self.assertFalse(initial.json()['automatic_dispatch'])
        self.assertEqual(initial.json()['candidates']['total'], 1)
        self.assertNotContains(initial, lead.phone)
        action = {'action': 'enqueue', 'assistant': 'yasaman', 'lead_id': lead.pk}
        self.assertEqual(self._post(**action).status_code, 200)
        self.assertEqual(self._post(**action).status_code, 200)
        self.assertEqual(self._post(**dict(action, assistant='rose')).status_code, 409)
        job = AssistantCallJob.objects.get()
        self.assertEqual(job.scheduled_for, self.due)
        self.assertEqual(AuditLog.objects.filter(action='assistant_queue_enqueue').count(), 1)
        self.assertEqual(self._post(action='pause', assistant='yasaman').status_code, 200)
        planned = self.client.get(self.url)
        self.assertNotContains(planned, lead.phone)
        payload = planned.json()
        self.assertTrue(payload['queues'][0]['paused'])
        self.assertEqual(payload['queues'][0]['queued_count'], 1)
        self.assertEqual(payload['candidates']['total'], 0)
        self.assertEqual(payload['jobs']['items'][0]['status'], 'queued')
        self.assertEqual(self._post(action='resume', assistant='yasaman').status_code, 200)
        self.assertEqual(self._post(action='cancel', job_id=job.pk).status_code, 200)
        self.assertEqual(self._post(action='cancel', job_id=job.pk).status_code, 200)
        self.assertEqual(self._post(**action).status_code, 409)
        cancelled = self.client.get(self.url, {'assistant': 'yasaman', 'status': 'cancelled'}).json()
        self.assertEqual(cancelled['jobs']['total'], 1)
        self.assertEqual(cancelled['queues'][0]['cancelled_count'], 1)
        self.assertFalse(cancelled['queues'][0]['paused'])
        self.assertEqual(AuditLog.objects.filter(action='assistant_queue_cancel').count(), 1)

    def test_revoked_consent_and_changed_agenda_are_blocked(self):
        first, second = self._lead(1), self._lead(2)
        for lead in (first, second):
            self.assertEqual(self._post(action='enqueue', assistant='rose', lead_id=lead.pk).status_code, 200)
        LeadCallProfile.objects.filter(lead=first).update(do_not_contact=True)
        ReferralLead.objects.filter(pk=second.pk).update(next_follow_up=self.due.date() + timedelta(days=1))
        result = self.client.get(self.url, {'status': 'blocked'}).json()
        self.assertEqual(result['jobs']['total'], 2)
        self.assertEqual(result['queues'][2]['blocked_count'], 2)
        self.assertEqual(result['queues'][2]['queued_count'], 0)
        self.assertEqual(result['candidates']['total'], 0)
        self.assertEqual(AssistantCallJob.objects.filter(status='queued').count(), 2)
        self.assertEqual(self._post(action='enqueue', assistant='rose', lead_id=second.pk).status_code, 409)

    def test_permission_boundaries_and_invalid_operations(self):
        self.client.force_login(self.manager)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['can_manage'])
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self._post(action='resume', assistant='rose').status_code, 403)
        self.client.force_login(self.worker)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.admin)
        self.assertEqual(self._post(action='enqueue', assistant='unknown', lead_id=1).status_code, 400)
        self.assertEqual(self._post(action='cancel', job_id=True).status_code, 400)

    def test_paginated_candidates_do_not_cap_total_requests(self):
        for index in range(1, 27):
            self._lead(index)
        response = self.client.get(self.url, {'candidate_page': 2})
        self.assertEqual(response.status_code, 200)
        page = response.json()['candidates']
        self.assertEqual((page['total'], page['pages'], page['page'], len(page['items'])), (26, 2, 2, 1))

    def test_queue_mutation_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.admin)
        result = client.post(
            self.url, {'action': 'pause', 'assistant': 'yasaman'}, content_type='application/json',
        )
        self.assertRedirects(result, self.url, fetch_redirect_response=False)
        self.assertFalse(client.get(self.url).json()['queues'][0]['paused'])
