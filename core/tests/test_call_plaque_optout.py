from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.call_plaque_models import LeadCallProfile
from core.models import EmployeeProfile, ReferralLead, ReferralProfile, SmsAutomationRule, SmsScheduledMessage
from core.sms_automation import CALL_EVENT_STATUSES, CALL_RESULT_SMS_EVENTS, process_due_sms, queue_call_result_sms


class CallPlaqueOptOutTests(TestCase):
    def setUp(self):
        self.operator = User.objects.create_user('plaque-optout-operator')
        self.operator_profile, _ = EmployeeProfile.objects.update_or_create(
            user=self.operator, defaults={'role': 'call_center', 'is_active': True},
        )
        referrer_user = User.objects.create_user('plaque-optout-referrer')
        referrer = ReferralProfile.objects.create(user=referrer_user, referral_code='OPTOUTTEST')
        self.lead = ReferralLead.objects.create(
            referrer=referrer, assigned_to=self.operator_profile,
            full_name='درخواست عدم تماس', phone='09123456789',
            status='contacted', contact_result='no_answer',
        )
        self.profile = LeadCallProfile.objects.create(lead=self.lead, do_not_contact=True)
        self.client.force_login(self.operator)

    def _queued_message(self, event='call_no_answer'):
        rule, _ = SmsAutomationRule.objects.get_or_create(
            event=event,
            defaults={'is_enabled': True, 'recipient': 'patient', 'message_template': 'سلام'},
        )
        return SmsScheduledMessage.objects.create(
            rule=rule, event_key=f'{event}:{self.lead.pk}-old:patient',
            number=self.lead.phone, body='سلام', due_at=timezone.now()-timedelta(minutes=1),
        )

    def test_call_start_rejects_opted_out_assigned_lead(self):
        response = self.client.post(reverse('call_center_mark_call_started', args=[self.lead.pk]))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['code'], 'do_not_contact')
        self.assertIn('تماس مجدد', response.json()['error'])
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.status, self.lead.contact_result), ('contacted', 'no_answer'))

    @patch('core.sms_automation.queue_call_result_sms')
    def test_legacy_result_cannot_reactivate_or_queue_messages(self, mocked_queue):
        original_updated_at = self.lead.updated_at
        for result in ('no_answer', 'not_interested', 'follow_up'):
            with self.subTest(result=result), self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(reverse('call_center_save_call_result', args=[self.lead.pk]), {
                    'result': result, 'follow_up_interval': 'days:1',
                })
                self.assertEqual(response.status_code, 409)
                self.assertEqual(response.json()['code'], 'do_not_contact')
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.status, self.lead.contact_result), ('contacted', 'no_answer'))
        self.assertEqual(self.lead.updated_at, original_updated_at)
        self.assertIsNone(self.lead.next_follow_up)
        mocked_queue.assert_not_called()

    def test_opt_out_does_not_expose_other_operators_leads(self):
        other_user = User.objects.create_user('plaque-optout-other')
        other_profile, _ = EmployeeProfile.objects.update_or_create(
            user=other_user, defaults={'role': 'call_center', 'is_active': True},
        )
        self.lead.assigned_to = other_profile
        self.lead.save(update_fields=['assigned_to'])
        for endpoint in ('call_center_mark_call_started', 'call_center_save_call_result'):
            with self.subTest(endpoint=endpoint):
                response = self.client.post(reverse(endpoint, args=[self.lead.pk]), {'result': 'no_answer'})
                self.assertEqual(response.status_code, 404)

    def test_queue_cancels_older_messages_and_suppresses_all_call_outcomes(self):
        for result, event in CALL_RESULT_SMS_EVENTS.items():
            with self.subTest(result=result):
                self.lead.contact_result = result
                self.lead.status = CALL_EVENT_STATUSES[result]
                self.lead.save(update_fields=['contact_result', 'status', 'updated_at'])
                old = self._queued_message(event)
                self.assertIsNone(queue_call_result_sms(self.lead.pk))
                old.refresh_from_db()
                self.assertEqual(old.status, 'cancelled')
        self.assertFalse(SmsScheduledMessage.objects.exclude(status='cancelled').exists())

    def test_existing_lead_without_plaque_keeps_normal_result_and_sms_queue(self):
        self.profile.delete()
        self.lead.status = 'new'
        self.lead.contact_result = ''
        self.lead.save(update_fields=['status', 'contact_result'])
        SmsAutomationRule.objects.create(
            event='call_no_answer', is_enabled=True, recipient='patient', message_template='سلام',
        )
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(reverse('call_center_save_call_result', args=[self.lead.pk]), {
                'result': 'no_answer',
            })
        self.assertEqual(response.status_code, 200)
        self.lead.refresh_from_db()
        self.assertEqual((self.lead.status, self.lead.contact_result), ('contacted', 'no_answer'))
        self.assertEqual(SmsScheduledMessage.objects.get().status, 'pending')

    @patch('core.sms.send_sms')
    def test_worker_cancels_previously_queued_call_even_when_outcome_still_matches(self, mocked_send):
        item = self._queued_message()
        self.assertEqual(process_due_sms(), 0)
        item.refresh_from_db()
        self.assertEqual(item.status, 'cancelled')
        mocked_send.assert_not_called()

    @patch('core.sms.send_sms')
    def test_worker_dispatches_permitted_call_outcome_normally(self, mocked_send):
        self.profile.do_not_contact = False
        self.profile.save(update_fields=['do_not_contact'])
        item = self._queued_message()
        self.assertEqual(process_due_sms(), 1)
        item.refresh_from_db()
        self.assertEqual(item.status, 'accepted')
        mocked_send.assert_called_once_with(self.lead.phone, 'سلام', purpose='manual')

    @patch('core.sms.send_sms')
    def test_worker_rechecks_opt_out_after_claim_before_gateway_dispatch(self, mocked_send):
        self.profile.do_not_contact = False
        self.profile.save(update_fields=['do_not_contact'])
        item = self._queued_message()

        def opt_out_when_claimed(sender, instance, **kwargs):
            if instance.pk == item.pk and instance.status == 'sending':
                LeadCallProfile.objects.filter(pk=self.profile.pk).update(do_not_contact=True)

        post_save.connect(opt_out_when_claimed, sender=SmsScheduledMessage)
        try:
            self.assertEqual(process_due_sms(), 0)
        finally:
            post_save.disconnect(opt_out_when_claimed, sender=SmsScheduledMessage)
        item.refresh_from_db()
        self.assertEqual(item.status, 'cancelled')
        mocked_send.assert_not_called()

    @patch('core.sms.send_sms')
    def test_existing_treatment_reminder_is_not_blocked_by_outbound_call_opt_out(self, mocked_send):
        item = self._queued_message('appointment_reminder')
        self.assertEqual(process_due_sms(), 1)
        item.refresh_from_db()
        self.assertEqual(item.status, 'accepted')
        mocked_send.assert_called_once_with(self.lead.phone, 'سلام', purpose='manual')
