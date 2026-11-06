"""No real gateway calls: scheduling, ownership, exits, quotas and reward idempotency."""
import json
from copy import deepcopy
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.bulk_sms_automations import (
    save_automation, change_automation, process_due_automations, validate_config,
)
from core.bulk_sms_dispatch import process_bulk_sms
from core.models import (
    ApiServerSettings, BulkSmsAutomation, BulkSmsAutomationRun, BulkSmsAutomationStep,
    BulkSmsParticipation, BulkSmsCampaign, BulkSmsRecipient, BulkSmsOptOut,
)


class BulkSmsAutomationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.owner = User.objects.create_superuser('sms-auto-owner', 'auto@example.com', 'password')
        cls.other = User.objects.create_superuser('sms-auto-other', 'other@example.com', 'password')
        cls.staff = User.objects.create_user('sms-auto-staff', password='password')

    def setUp(self):
        self.client.force_login(self.owner)
        self.now = timezone.now()
        self.numbers = ['09120000001', '09120000002']
        self.exits = []
        self.start = self.now + timedelta(hours=1)
        self.config = {
            'segments':['lead_all'], 'exclude_segments':[], 'combine':'any',
            'start_at':self.start.isoformat(), 'end_at':None, 'interval_days':0,
            'limit':100, 'daily_limit':100, 'inactive_days':0,
            'reward':{'enabled':False,'points':0,'title':''},
            'steps':[{'body':'پیام تست گرین‌لایف {لینک}','delay_days':0,'condition':'all'}],
        }
        gateway = ApiServerSettings.load()
        gateway.is_enabled = True
        gateway.api_key_cipher = 'configured-test-only'
        gateway.save(update_fields=['is_enabled','api_key_cipher'])
        self.audience = patch('core.bulk_sms_automations.audience_preview', side_effect=self.fake_audience)
        self.audience.start()
        self.addCleanup(self.audience.stop)

    def fake_audience(self, keys, **kwargs):
        nums = self.exits if keys == ['visit_booked'] else self.numbers
        return {'_numbers':list(nums), 'count':len(nums), 'truncated':False}

    def create(self, activate=True, config=None):
        item = save_automation(user=self.owner, name='کمپین آزمایشی', data=config or self.config)
        if activate:
            item = change_automation(user=self.owner, item_id=item.pk, action='activate',
                                     revision=item.revision, consent=True, typed='تایید')
        return item

    def run_due(self, when=None):
        with patch('core.bulk_sms_automations.timezone.now', return_value=when or self.start):
            process_due_automations()

    def send(self, when=None):
        with patch('core.bulk_sms_automations.timezone.now', return_value=when or self.start):
            with patch('core.sms.send_sms') as sender:
                process_bulk_sms()
                return sender

    def post(self, data):
        return self.client.post(reverse('bulk_sms_automations_api'), data=json.dumps(data), content_type='application/json')

    def test_draft_preview_and_get_never_queue_or_send(self):
        item = self.create(activate=False)
        self.assertEqual(self.post({'action':'preview','config':self.config}).status_code,200)
        self.assertEqual(self.client.get(reverse('bulk_sms_automations_api')).status_code,200)
        self.run_due(self.start+timedelta(days=1))
        self.assertEqual(item.status,'draft')
        self.assertFalse(BulkSmsCampaign.objects.exists())

    def test_activation_requires_consent_revision_and_future_start(self):
        item = self.create(activate=False)
        for payload in [dict(consent=False,typed='تایید'),dict(consent=True,typed='')]:
            with self.assertRaises(ValueError):
                change_automation(user=self.owner,item_id=item.pk,action='activate',**payload)
        with self.assertRaises(ValueError):
            change_automation(user=self.owner,item_id=item.pk,action='activate',consent=True,typed='تایید',revision=999)
        self.config['start_at']=(self.now-timedelta(hours=1)).isoformat()
        past=self.create(activate=False)
        with self.assertRaises(ValueError):
            change_automation(user=self.owner,item_id=past.pk,action='activate',consent=True,typed='تایید')

    def test_due_schedule_is_idempotent_and_tehran_datetime_is_aware(self):
        self.create()
        self.run_due(self.start-timedelta(seconds=1))
        self.assertFalse(BulkSmsAutomationRun.objects.exists())
        self.run_due(); self.run_due()
        self.assertEqual(BulkSmsAutomationRun.objects.count(),1)
        self.assertEqual(BulkSmsAutomationStep.objects.count(),1)
        self.assertEqual(BulkSmsRecipient.objects.count(),2)
        self.assertEqual(BulkSmsCampaign.objects.get().status,'queued')
        plain=deepcopy(self.config);plain['start_at']='2027-03-21T11:00'
        self.assertTrue(validate_config(plain)['start_at'].endswith('+03:30'))

    def test_dynamic_membership_exit_and_optout_checked_before_send(self):
        self.config['exclude_segments']=['visit_booked'];self.create();self.run_due()
        self.exits=[self.numbers[0]]
        BulkSmsOptOut.objects.create(number=self.numbers[1])
        sender=self.send()
        sender.assert_not_called()
        self.assertEqual(BulkSmsRecipient.objects.filter(status='skipped').count(),2)

    def test_cohort_cap_and_daily_cap(self):
        self.config['daily_limit']=1;self.create();self.run_due()
        self.assertEqual(self.send().call_count,1)
        self.assertEqual(self.send().call_count,0)
        self.assertEqual(BulkSmsRecipient.objects.filter(status='pending').count(),1)
        self.assertEqual(self.send(self.start+timedelta(days=1,seconds=1)).call_count,1)

    def test_pause_resume_and_end_control_pending_queue(self):
        item=self.create();self.run_due()
        item=change_automation(user=self.owner,item_id=item.pk,action='pause')
        self.assertEqual(BulkSmsCampaign.objects.get().status,'paused')
        self.send().assert_not_called()
        change_automation(user=self.owner,item_id=item.pk,action='activate',consent=True,typed='تایید')
        self.assertEqual(BulkSmsCampaign.objects.get().status,'queued')
        change_automation(user=self.owner,item_id=item.pk,action='end')
        self.assertEqual(BulkSmsRecipient.objects.filter(status='skipped').count(),2)
        self.assertEqual(BulkSmsAutomationRun.objects.get().status,'cancelled')

    def test_end_date_cancels_outstanding_messages(self):
        self.config['end_at']=(self.start+timedelta(hours=2)).isoformat()
        self.create();self.run_due();self.run_due(self.start+timedelta(hours=3))
        self.assertEqual(BulkSmsAutomation.objects.get().status,'ended')
        self.assertEqual(BulkSmsRecipient.objects.filter(status='skipped').count(),2)

    def test_editing_a_running_definition_is_rejected(self):
        item=self.create();self.run_due()
        with self.assertRaises(ValueError):
            save_automation(user=self.owner,name='edited',data=self.config,item_id=item.pk,revision=item.revision)
        item=change_automation(user=self.owner,item_id=item.pk,action='pause')
        with self.assertRaises(ValueError):
            save_automation(user=self.owner,name='edited',data=self.config,item_id=item.pk,revision=item.revision)

    def test_recurrence_does_not_replay_missed_intervals(self):
        self.config['interval_days']=7;self.create();self.run_due(self.start+timedelta(days=22))
        item=BulkSmsAutomation.objects.get()
        self.assertEqual(item.next_run_at,self.start+timedelta(days=28))
        self.assertEqual(item.runs.count(),1)

    def test_followup_waits_for_previous_delivery_and_filters_participation(self):
        self.config['steps'].append({'body':'یادآوری کمپین','delay_days':7,'condition':'unengaged'})
        self.create();self.run_due();self.send(self.start+timedelta(days=2))
        participant=BulkSmsParticipation.objects.get(number=self.numbers[0]);participant.participated_at=self.start;participant.save()
        self.run_due(self.start+timedelta(days=7,seconds=1))
        self.assertEqual(BulkSmsCampaign.objects.count(),1)
        self.run_due(self.start+timedelta(days=9,seconds=1))
        self.assertEqual(BulkSmsCampaign.objects.count(),2)
        last=BulkSmsCampaign.objects.latest('id')
        self.assertEqual(list(last.recipients.values_list('number',flat=True)),[self.numbers[1]])

    def test_tracking_get_is_readonly_and_post_awards_once(self):
        self.config['reward']={'enabled':True,'points':20,'title':'هدیه باشگاه'}
        self.create();self.run_due();self.send()
        person=BulkSmsParticipation.objects.first();url=reverse('bulk_sms_participate',args=[person.token])
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code,200)
        person.refresh_from_db();self.assertIsNone(person.participated_at)
        self.assertEqual(self.client.post(url).status_code,200)
        self.assertEqual(self.client.post(url).status_code,200)
        person.refresh_from_db();self.assertEqual(person.points,20)

    def test_cancelled_and_unsent_links_do_not_award(self):
        self.config['reward']={'enabled':True,'points':20,'title':''}
        item=self.create();self.run_due()
        person=BulkSmsParticipation.objects.first();url=reverse('bulk_sms_participate',args=[person.token])
        self.client.post(url);person.refresh_from_db();self.assertEqual(person.points,0)
        self.send();change_automation(user=self.owner,item_id=item.pk,action='end')
        self.client.post(url);person.refresh_from_db();self.assertEqual(person.points,0)

    def test_each_recipient_gets_own_link(self):
        self.create();self.run_due();sender=self.send()
        bodies=[c.args[1] for c in sender.call_args_list]
        self.assertEqual(len(set(bodies)),2)
        for person in BulkSmsParticipation.objects.all():
            self.assertTrue(any(str(person.token) in body for body in bodies))

    def test_permissions_and_owner_isolation(self):
        item=self.create(activate=False)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse('bulk_sms_automations_api')).json()['automations'],[])
        self.assertEqual(self.client.get(reverse('bulk_sms_automation_report',args=[item.pk])).status_code,404)
        self.assertEqual(self.post({'action':'pause','id':item.pk,'revision':item.revision}).status_code,400)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('bulk_sms_automations_api')).status_code,403)
        self.assertEqual(self.post({'action':'preview','config':self.config}).status_code,403)

    def test_revoked_owner_cannot_continue_sending(self):
        item=self.create();self.run_due()
        User.objects.filter(pk=self.owner.pk).update(is_active=False)
        self.send().assert_not_called()

    def test_invalid_configs_fail_closed(self):
        for key,value in [('segments',[]),('daily_limit',401),('limit',2501),('interval_days',1),('inactive_days',-1)]:
            config=deepcopy(self.config);config[key]=value
            with self.subTest(key=key),self.assertRaises(ValueError): validate_config(config)
        config=deepcopy(self.config);config['reward']['enabled']=True;config['steps'][0]['body']='بدون لینک'
        with self.assertRaises(ValueError): validate_config(config)

    def test_history_identifies_automatic_steps_and_filters(self):
        self.create();self.run_due()
        automatic=self.client.get(reverse('bulk_sms_campaigns_status_api')+'?mode=auto').json()
        self.assertEqual(len(automatic['campaigns']),1)
        self.assertEqual(automatic['campaigns'][0]['step'],1)
        self.assertEqual(automatic['campaigns'][0]['source'],'auto')
        self.assertEqual(self.client.get(reverse('bulk_sms_campaigns_status_api')+'?mode=manual').json()['campaigns'],[])
