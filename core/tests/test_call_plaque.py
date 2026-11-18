import json
import uuid
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.call_plaque import call_plaque_summaries, empty_data, score_readiness
from core.models import AuditLog, Branch, EmployeeProfile, LeadCallProfile, LeadCallSession, LeadFollowUpLog, ReferralLead, ReferralProfile


class CallPlaqueTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='مرکز تست پلاک')
        self.other_branch = Branch.objects.create(name='شعبه دیگر پلاک')
        self.operator = self.user('plaque-op', 'call_center')
        self.other_operator = self.user('plaque-other', 'call_center')
        self.admin = self.user('plaque-admin', 'admin')
        self.manager = self.user('plaque-manager', 'manager')
        self.internal = self.user('plaque-internal', 'internal_manager')
        self.staff = self.user('plaque-staff', 'employee')
        referrer = ReferralProfile.objects.create(user=self.staff, referral_code='PLAQUE-TEST', created_by=self.staff)
        self.lead = ReferralLead.objects.create(referrer=referrer, full_name='لید آزمایشی پلاک', phone='09121111111', assigned_to=self.operator.profile)
        self.other_lead = ReferralLead.objects.create(referrer=referrer, full_name='لید دیگر', phone='09121111112', assigned_to=self.other_operator.profile)
        self.url = reverse('call_center_call_plaque', args=[self.lead.pk])
        self.client.force_login(self.operator)

    def user(self, username, role):
        user = User.objects.create_user(username, password='test-pass')
        EmployeeProfile.objects.update_or_create(user=user, defaults={'role': role, 'branch': self.branch, 'is_active': True})
        return User.objects.get(pk=user.pk)

    def post(self, data=None, *, action='finalize', version=0, request_id=None, client=None):
        return (client or self.client).post(self.url, data=json.dumps({
            'action': action, 'version': version, 'request_id': str(request_id or uuid.uuid4()),
            'data': empty_data() if data is None else data,
        }), content_type='application/json')

    def answered(self):
        data = empty_data()
        data.update(outcome='answered', operator_rating=4, operator_reason='خودش اطلاعات بیشتر خواست',
                    communication_style='details', communication_evidence='درباره روش و محدودیت پرسید')
        data['answers'].update({
            'goal': {'state': 'answered', 'value': 'آشنایی با خدمات'},
            'priority': {'state': 'answered', 'value': 'اطمینان و توضیح دقیق'},
            'timing': {'state': 'answered', 'value': 'soon'},
            'barrier': {'state': 'answered', 'value': 'uncertainty'},
        })
        return data

    def test_get_does_not_create_records_and_new_score_is_unknown(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['editable'])
        self.assertEqual(payload['version'], 0)
        self.assertIsNone(payload['profile']['readiness']['score'])
        self.assertIsNone(payload['draft'])
        self.assertEqual(payload['history'], [])
        self.assertFalse(LeadCallProfile.objects.exists())
        self.assertNotIn(self.lead.phone, response.content.decode())
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_own_lead_only_and_active_role_enforced(self):
        other_url = reverse('call_center_call_plaque', args=[self.other_lead.pk])
        self.assertEqual(self.client.get(other_url).status_code, 404)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(self.url).status_code, 403)
        self.client.force_login(self.operator)
        EmployeeProfile.objects.filter(user=self.operator).update(is_active=False)
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_admin_read_only_and_manager_branch_scope(self):
        self.client.force_login(self.admin)
        self.assertFalse(self.client.get(self.url).json()['editable'])
        self.assertEqual(self.post(self.answered()).status_code, 403)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        EmployeeProfile.objects.filter(user=self.manager).update(branch=self.other_branch)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_draft_resume_discard_does_not_count_as_call_or_change_lead(self):
        before = {name: getattr(self.lead, name) for name in ('status', 'contact_result', 'next_follow_up', 'updated_at', 'notes')}
        data = empty_data()
        data['notes'] = 'پیش‌نویس واقعی؛ هنوز تماسی انجام نشده'
        saved = self.post(data, action='save_draft')
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(saved.json()['version'], 1)
        reopened = self.client.get(self.url).json()
        self.assertEqual(reopened['draft']['data']['notes'], data['notes'])
        self.assertEqual(reopened['history_total'], 0)
        self.assertIsNone(reopened['profile']['readiness']['score'])
        self.lead.refresh_from_db()
        for name, value in before.items():
            self.assertEqual(getattr(self.lead, name), value)
        self.assertFalse(LeadFollowUpLog.objects.exists())
        discarded = self.post(action='discard_draft', version=1)
        self.assertEqual(discarded.status_code, 200)
        self.assertIsNone(self.client.get(self.url).json()['draft'])
        self.assertEqual(LeadCallSession.objects.filter(state='final').count(), 0)

    def test_drafts_do_not_leak_after_owner_transfer(self):
        data = empty_data()
        data['notes'] = 'پیش‌نویس کارشناس اول'
        self.post(data, action='save_draft')
        ReferralLead.objects.filter(pk=self.lead.pk).update(assigned_to=self.other_operator.profile)
        self.client.force_login(self.other_operator)
        payload = self.client.get(self.url).json()
        self.assertIsNone(payload['draft'])
        self.assertNotIn('پیش‌نویس کارشناس اول', json.dumps(payload, ensure_ascii=False))

    def test_finalize_creates_immutable_history_and_preserves_original_ownership(self):
        data = self.answered()
        original_notes = 'شرح قدیمی'
        ReferralLead.objects.filter(pk=self.lead.pk).update(notes=original_notes, first_appointment_by=self.other_operator)
        response = self.post(data)
        self.assertEqual(response.status_code, 200)
        event = LeadCallSession.objects.get(state='final')
        initial_data = deepcopy(event.data)
        self.assertEqual(response.json()['history_total'], 1)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.assigned_to_id, self.operator.profile.pk)
        self.assertEqual(self.lead.first_appointment_by_id, self.other_operator.pk)
        self.assertEqual(self.lead.notes, original_notes)
        second = empty_data()
        second['outcome'] = 'answered'
        second['answers']['priority'] = {'state': 'answered', 'value': 'زمان مراجعه'}
        self.assertEqual(self.post(second, version=1).status_code, 200)
        event.refresh_from_db()
        self.assertEqual(event.data, initial_data)
        latest = self.client.get(self.url).json()
        self.assertEqual(latest['history_total'], 2)
        self.assertEqual(latest['profile']['answers']['goal']['value'], 'آشنایی با خدمات')
        self.assertEqual(latest['profile']['answers']['priority']['value'], 'زمان مراجعه')
        self.assertIn('priority', latest['profile']['evidence'])

    def test_version_check_and_idempotency_prevent_duplicate_call(self):
        data = self.answered()
        key = uuid.uuid4()
        first = self.post(data, request_id=key)
        self.assertEqual(first.status_code, 200)
        replay = self.post(data, request_id=key)
        self.assertEqual(replay.status_code, 200)
        self.assertTrue(replay.json()['replayed'])
        self.assertEqual(replay.json()['saved'], 'final')
        self.assertEqual(LeadCallSession.objects.filter(state='final').count(), 1)
        self.assertEqual(LeadFollowUpLog.objects.count(), 1)
        stale = self.post(data, version=0)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(stale.json()['code'], 'stale_version')
        data['notes'] = 'محتوای متفاوت با شناسه تکراری'
        self.assertEqual(self.post(data, request_id=key, version=1).status_code, 409)

    def test_request_id_for_another_lead_is_not_reused(self):
        key = uuid.uuid4()
        self.post(self.answered(), request_id=key)
        self.client.force_login(self.other_operator)
        self.url = reverse('call_center_call_plaque', args=[self.other_lead.pk])
        self.assertEqual(self.post(self.answered(), request_id=key).status_code, 409)

    def test_followup_needs_separate_consent_and_agreed_time(self):
        data = self.answered()
        data['outcome'] = 'follow_up'
        self.assertEqual(self.post(data).status_code, 400)
        data['whatsapp_consent'] = 'yes'
        self.assertEqual(self.post(data).status_code, 400)
        data['followup_consent'] = 'yes'
        self.assertEqual(self.post(data).status_code, 400)
        agreed = timezone.now() + timedelta(days=7)
        data['followup_at'] = agreed.isoformat()
        response = self.post(data)
        self.assertEqual(response.status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.next_follow_up, timezone.localtime(agreed).date())
        self.assertEqual(self.lead.contact_result, 'follow_up')

    def test_no_answer_preserves_readiness_and_agreement_without_new_consent(self):
        data = self.answered()
        data.update(outcome='follow_up', followup_consent='yes', followup_at=(timezone.now() + timedelta(days=7)).isoformat())
        first = self.post(data).json()
        before_score = first['profile']['readiness']
        missed = empty_data()
        missed['outcome'] = 'no_answer'
        response = self.post(missed, version=1)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertEqual(payload['profile']['readiness'], before_score)
        self.assertEqual(parse_datetime(payload['profile']['followup_at']), parse_datetime(data['followup_at']))
        self.assertEqual(payload['history'][0]['data']['followup_consent'], 'unknown')
        self.assertEqual(payload['profile']['answers']['priority']['value'], data['answers']['priority']['value'])

    def test_no_answer_cannot_claim_new_answers_or_assessment(self):
        data = self.answered()
        data['outcome'] = 'no_answer'
        self.assertEqual(self.post(data).status_code, 400)
        self.assertFalse(LeadCallSession.objects.exists())

    def test_wrong_number_closes_queue_with_accurate_result(self):
        data = empty_data()
        data['outcome'] = 'wrong_number'
        response = self.post(data)
        self.assertEqual(response.status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'lost')
        self.assertEqual(self.lead.contact_result, 'wrong_number')
        self.assertEqual(response.json()['history'][0]['outcome'], 'wrong_number')
        self.assertIsNone(response.json()['profile']['readiness']['score'])

    def test_do_not_contact_is_durable_and_overrides_readiness(self):
        data = self.answered()
        data.update(outcome='do_not_contact', do_not_contact=True)
        response = self.post(data)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['profile']['do_not_contact'])
        self.assertEqual(response.json()['profile']['readiness']['band'], 'stop')
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'lost')
        self.assertIsNone(self.lead.next_follow_up)
        attempted_reopen = self.answered()
        attempted_reopen.update(outcome='follow_up', followup_consent='yes', followup_at=(timezone.now() + timedelta(days=2)).isoformat())
        self.assertEqual(self.post(attempted_reopen, version=1).status_code, 400)
        update = empty_data()
        update.update(outcome='answered', notes='توضیح تکمیلی بدون رفع عدم تماس')
        self.assertEqual(self.post(update, version=1).status_code, 200)
        self.assertTrue(LeadCallProfile.objects.get(lead=self.lead).do_not_contact)

    def test_finalized_call_does_not_send_sms_or_regress_appointment_status(self):
        ReferralLead.objects.filter(pk=self.lead.pk).update(status='appointment', contact_result='appointment', first_appointment_by=self.other_operator)
        data = empty_data()
        data['outcome'] = 'no_answer'
        with patch('core.sms_automation.queue_call_result_sms') as queue:
            with self.captureOnCommitCallbacks(execute=True):
                response = self.post(data)
        self.assertEqual(response.status_code, 200)
        queue.assert_not_called()
        self.lead.refresh_from_db()
        self.assertEqual(self.lead.status, 'appointment')
        self.assertEqual(self.lead.contact_result, 'appointment')
        self.assertEqual(self.lead.first_appointment_by_id, self.other_operator.pk)

    def test_followup_refusal_clears_callback_but_preserves_appointment(self):
        ReferralLead.objects.filter(pk=self.lead.pk).update(
            status='appointment', contact_result='appointment',
            next_follow_up=timezone.localdate() + timedelta(days=7),
        )
        data = self.answered()
        data['followup_consent'] = 'no'
        response = self.post(data)
        self.assertEqual(response.status_code, 200)
        self.lead.refresh_from_db()
        self.assertIsNone(self.lead.next_follow_up)
        self.assertIsNone(self.lead.next_follow_up_time)
        self.assertEqual(self.lead.status, 'appointment')
        self.assertEqual(self.lead.contact_result, 'appointment')

    def test_restricted_management_payload_masks_private_answers_and_free_text(self):
        data = self.answered()
        data['notes'] = 'PRIVATE-NOTE 09125556666'
        data['answers']['goal']['value'] = 'PRIVATE-GOAL'
        data['answers']['priority']['value'] = 'PRIVATE-PRIORITY'
        data['answers']['height_cm'] = {'state': 'answered', 'value': '175'}
        data['answers']['weight_kg'] = {'state': 'answered', 'value': '84.5'}
        data['answers']['budget_fit'] = {'state': 'answered', 'value': 'suitable'}
        self.assertEqual(self.post(data).status_code, 200)
        self.client.force_login(self.internal)
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload['restricted'])
        self.assertFalse(payload['editable'])
        for key in ('goal', 'priority', 'height_cm', 'weight_kg', 'budget_fit'):
            self.assertNotIn(key, payload['profile']['answers'])
            self.assertNotIn(key, payload['history'][0]['data']['answers'])
        for value in ('PRIVATE-NOTE', '09125556666', 'PRIVATE-GOAL', 'PRIVATE-PRIORITY', 'operator_reason', 'communication_evidence'):
            self.assertNotIn(value, response.content.decode())
        self.assertIn('timing', payload['profile']['answers'])
        self.client.force_login(self.admin)
        self.assertIn('PRIVATE-GOAL', self.client.get(self.url).content.decode())

    def test_body_schema_invalid_data_and_fake_conversion_rejected(self):
        for change in ({'outcome': 'won'}, {'operator_rating': 8}, {'communication_style': 'D'},
                       {'whatsapp_consent': []}, {'outcome': 'appointment'}):
            data = self.answered()
            data.update(change)
            with self.subTest(change=change):
                self.assertEqual(self.post(data).status_code, 400)
        data = self.answered()
        data['answers']['diagnosis'] = {'state': 'answered', 'value': 'unsupported'}
        self.assertEqual(self.post(data).status_code, 400)
        self.assertFalse(LeadCallSession.objects.exists())

    def test_ratings_are_independent_and_unasked_preserves_each_previous_value(self):
        data = self.answered()
        answers = data['answers']
        answers['interest'] = {'state': 'answered', 'value': '5'}
        answers['budget_fit'] = {'state': 'answered', 'value': '2'}
        self.assertEqual(self.post(data).status_code, 200)
        second = empty_data()
        second['outcome'] = 'answered'
        second['answers']['interest'] = {'state': 'answered', 'value': '3'}
        result = self.post(second, version=1).json()
        self.assertEqual(result['profile']['answers']['budget_fit'], answers['budget_fit'])
        self.assertEqual(result['profile']['answers']['interest']['value'], '3')
        self.assertEqual(result['history'][1]['data']['answers']['interest']['value'], '5')

    def test_replay_from_before_star_ratings_preserves_old_snapshot(self):
        data = self.answered()
        request_id = uuid.uuid4()
        del data['answers']['interest']
        self.assertEqual(self.post(data, request_id=request_id).status_code, 200)
        session = LeadCallSession.objects.get(request_id=request_id)
        del session.data['answers']['interest']
        session.save(update_fields=['data'])
        retry = self.post(data, request_id=request_id)
        self.assertTrue(retry.json()['replayed'])
        session.refresh_from_db()
        self.assertNotIn('interest', session.data['answers'])

    def test_csrf_is_required(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.operator)
        response = self.post(self.answered(), client=client)
        # Existing project CSRF recovery redirects authenticated failures to GET.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers['Location'], self.url)
        self.assertFalse(LeadCallSession.objects.exists())
        self.assertFalse(LeadCallProfile.objects.exists())

    def test_medical_measures_budget_and_operator_rating_do_not_change_system_score(self):
        data = self.answered()
        before = score_readiness(data)
        data['answers']['height_cm'] = {'state': 'answered', 'value': '190'}
        data['answers']['weight_kg'] = {'state': 'answered', 'value': '160'}
        data['answers']['budget_fit'] = {'state': 'answered', 'value': 'suitable'}
        data['operator_rating'] = 1
        data['communication_style'] = 'direct'
        self.assertEqual(score_readiness(data), before)

    def test_bulk_summary_is_one_query_and_ignores_draft_score(self):
        self.post(self.answered(), action='save_draft')
        with self.assertNumQueries(1):
            summaries = call_plaque_summaries([self.lead.pk, self.other_lead.pk])
        self.assertIsNone(summaries[self.lead.pk]['score'])
        self.assertNotIn(self.other_lead.pk, summaries)

    def test_disc_codes_reflect_finalized_style_without_guessing_legacy_mixed(self):
        data = self.answered()
        for version, style in enumerate(('direct', 'mixed', 'DS', 'DC', 'CD')):
            data['communication_style'] = style
            response = self.post(data, version=version)
            self.assertEqual(response.status_code, 200)
            expected = {'direct':'D', 'mixed':''}.get(style, style)
            self.assertEqual(response.json()['profile']['disc_code'], expected)
            self.assertEqual(call_plaque_summaries([self.lead.pk])[self.lead.pk]['disc_code'], expected)
        data['communication_style'] = 'DD'
        self.assertEqual(self.post(data, version=5).status_code, 400)
