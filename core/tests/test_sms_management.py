from datetime import datetime, timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import (SmsAutomationRule, SmsScheduledMessage, ReferralProfile,
                         ReferralLead, EmployeeProfile)
from core.sms_automation import process_due_sms, schedule_sms_event


@override_settings(ROOT_URLCONF='greenlife.urls', EXECUTIVE_USERNAMES=('sms-exec',))
class SmsManagementTests(TestCase):
    def setUp(self):
        self.admin=User.objects.create_superuser('sms-exec','sms@example.com','SafePass123')
        self.client.force_login(self.admin)

    def test_manager_has_selectable_event_catalog(self):
        response=self.client.get(reverse('sms_management'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'مدیریت پیامک')
        self.assertContains(response,'یادآوری جلسه دستگاه')
        self.assertContains(response,'تأیید پرداخت')

    def test_connected_rule_can_be_enabled(self):
        response=self.client.post(reverse('sms_management'),{
            'event':'appointment_reminder','is_enabled':'on',
            'recipient':'patient','timing':'before','offset':'2',
            'offset_unit':'hours',
            'message_template':'{name} عزیز؛ نوبت شما ساعت {time} است.',
        })
        self.assertEqual(response.status_code,302)
        rule=SmsAutomationRule.objects.get(event='appointment_reminder')
        self.assertTrue(rule.is_enabled)
        self.assertEqual(rule.offset,2)

    def test_unconnected_rule_cannot_enable_live_sending(self):
        self.client.post(reverse('sms_management'),{
            'event':'device_session_finished','is_enabled':'on',
            'recipient':'custom','custom_number':'09123456789',
            'timing':'immediate','offset':'0','offset_unit':'minutes',
            'message_template':'مبلغ {amount}',
        })
        self.assertFalse(SmsAutomationRule.objects.get(event='device_session_finished').is_enabled)

    def test_bad_custom_number_is_rejected(self):
        self.client.post(reverse('sms_management'),{
            'event':'appointment_reminder','is_enabled':'on',
            'recipient':'custom','custom_number':'1234',
            'timing':'immediate','offset':'0','offset_unit':'minutes',
            'message_template':'سلام',
        })
        self.assertFalse(SmsAutomationRule.objects.filter(event='appointment_reminder').exists()
                         and SmsAutomationRule.objects.get(event='appointment_reminder').is_enabled)

    def test_disabled_rule_never_queues(self):
        SmsAutomationRule.objects.create(event='appointment_reminder',message_template='سلام')
        self.assertIsNone(schedule_sms_event('appointment_reminder',99,patient_number='09123456789'))
        self.assertFalse(SmsScheduledMessage.objects.exists())

    def test_delayed_event_is_idempotent(self):
        SmsAutomationRule.objects.create(
            event='appointment_reminder',is_enabled=True,recipient='patient',
            timing='before',offset=2,offset_unit='hours',
            message_template='{name} عزیز، ساعت {time}',
        )
        event_at=timezone.now()+timedelta(days=1)
        kwargs={'event_at':event_at,'patient_number':'09123456789',
                'context':{'name':'مراجع','time':'10:30'}}
        first=schedule_sms_event('appointment_reminder',77,**kwargs)
        second=schedule_sms_event('appointment_reminder',77,**kwargs)
        self.assertEqual(first.pk,second.pk)
        self.assertEqual(SmsScheduledMessage.objects.count(),1)
        self.assertEqual(first.due_at,event_at-timedelta(hours=2))

    @patch('core.sms.send_sms')
    def test_worker_dispatches_due_message_once(self,mocked_send):
        rule=SmsAutomationRule.objects.create(
            event='appointment_reminder',is_enabled=True,recipient='patient',
            message_template='سلام',
        )
        SmsScheduledMessage.objects.create(
            rule=rule,event_key='reminder:5:patient',
            number='09123456789',body='سلام',
            due_at=timezone.now()-timedelta(minutes=1),
        )
        self.assertEqual(process_due_sms(),1)
        self.assertEqual(process_due_sms(),0)
        self.assertEqual(mocked_send.call_count,1)
        self.assertEqual(SmsScheduledMessage.objects.get().status,'accepted')


    def test_call_outcome_rules_are_separate_and_off_by_default(self):
        response=self.client.get(reverse('sms_management'))
        for label in ('پاسخ نداد','تمایل ندارد','نیاز به پیگیری','نوبت داده شد'):
            self.assertContains(response,label)
        self.assertFalse(SmsAutomationRule.objects.filter(event__startswith='call_').exists())

    def test_no_answer_rule_can_be_configured_independently(self):
        response=self.client.post(reverse('sms_management'),{
            'event':'call_no_answer','is_enabled':'on',
            'recipient':'patient','timing':'after','offset':'5',
            'offset_unit':'minutes',
            'message_template':'{name} عزیز، با شما تماس گرفتیم. گرین لایف 02134247',
        })
        self.assertEqual(response.status_code,302)
        rule=SmsAutomationRule.objects.get(event='call_no_answer')
        self.assertTrue(rule.is_enabled)
        self.assertEqual(rule.offset,5)
        self.assertFalse(SmsAutomationRule.objects.filter(event='call_not_interested').exists())

    @patch('core.sms.send_sms')
    def test_worker_cancels_call_sms_when_lead_no_longer_exists(self,mocked_send):
        rule=SmsAutomationRule.objects.create(
            event='call_no_answer',is_enabled=True,recipient='patient',
            message_template='سلام',
        )
        item=SmsScheduledMessage.objects.create(
            rule=rule,event_key='call_no_answer:999999-20260928150000000000:patient',
            number='09123456789',body='سلام',
            due_at=timezone.now()-timedelta(minutes=1),
        )
        self.assertEqual(process_due_sms(),0)
        item.refresh_from_db()
        self.assertEqual(item.status,'cancelled')
        mocked_send.assert_not_called()


    def test_real_call_result_queues_and_new_result_cancels_old_pending_sms(self):
        referrer=User.objects.create_user('sms-referrer')
        ref_profile=ReferralProfile.objects.create(
            user=referrer,referral_code='SMSREF0001',
        )
        operator=User.objects.create_user('sms-operator',password='SafePass123')
        operator_profile=EmployeeProfile.objects.create(
            user=operator,role='call_center',phone='09121111111',
        )
        lead=ReferralLead.objects.create(
            referrer=ref_profile,full_name='مراجع آزمایشی',
            phone='09123456789',assigned_to=operator_profile,
        )
        SmsAutomationRule.objects.create(
            event='call_no_answer',is_enabled=True,recipient='patient',
            timing='after',offset=5,offset_unit='minutes',
            message_template='{name} عزیز، تماس گرفتیم.',
        )
        SmsAutomationRule.objects.create(
            event='call_not_interested',is_enabled=True,recipient='patient',
            timing='after',offset=5,offset_unit='minutes',
            message_template='درخواست شما ثبت شد.',
        )
        self.client.force_login(operator)
        url=reverse('call_center_save_call_result',args=[lead.pk])
        with self.captureOnCommitCallbacks(execute=True):
            first=self.client.post(url,{'result':'no_answer'})
        self.assertEqual(first.status_code,200)
        old=SmsScheduledMessage.objects.get(rule__event='call_no_answer')
        self.assertEqual(old.status,'pending')
        with self.captureOnCommitCallbacks(execute=True):
            second=self.client.post(url,{'result':'not_interested'})
        self.assertEqual(second.status_code,200)
        old.refresh_from_db()
        self.assertEqual(old.status,'cancelled')
        self.assertEqual(
            SmsScheduledMessage.objects.filter(
                rule__event='call_not_interested',status='pending',
            ).count(),1,
        )
