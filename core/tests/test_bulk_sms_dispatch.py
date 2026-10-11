"""Regression coverage: no send without separate approval; no duplicate marketing sends."""
import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.bulk_sms_dispatch import prepare_campaign, approve_campaign, process_bulk_sms
from core.models import (
    ApiServerSettings, BulkSmsCampaign, BulkSmsRecipient, BulkSmsOptOut,
    Country, EmployeeProfile, ReferralLead, ReferralProfile,
)


class BulkSmsDispatchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.country=Country.objects.get_or_create(
            code='IR',defaults={'name_english':'Iran','name_local':'ایران'},
        )[0]
        cls.executive=User.objects.create_superuser('bulk-executive','bulk-owner@example.com','password')
        cls.staff=User.objects.create_user('bulk-staff',password='password')
        EmployeeProfile.objects.filter(user=cls.staff).update(role='receptionist',is_active=True)
        cls.ref_user=User.objects.create_user('bulk-source',password='password')
        cls.referral=ReferralProfile.objects.create(
            user=cls.ref_user,referral_code='BLKSOURCE001',phone='09120001111',
        )
        cls.lead=ReferralLead.objects.create(
            country=cls.country,referrer=cls.referral,
            full_name='آزمایش کمپین',phone='09120001111',status='new',
        )

    def setUp(self):
        self.client.force_login(self.executive)
        gateway=ApiServerSettings.load()
        gateway.is_enabled=True
        gateway.api_key_cipher='configured-but-only-mocked-in-tests'
        gateway.save(update_fields=['is_enabled','api_key_cipher'])

    def post_json(self,body,*,client=None):
        return (client or self.client).post(
            reverse('bulk_sms_campaign_api'),
            data=json.dumps(body),content_type='application/json',
        )

    def test_preparation_is_read_only_then_explicit_approval_sends_through_worker(self):
        with patch('core.sms.send_sms') as sender:
            prepared=self.post_json({
                'action':'prepare','segments':['lead_all'],'combine':'all',
                'date_filter':{'preset':'all'},
                'body':'گرین لایف؛ برای اطلاع از خدمات ما تماس بگیرید.',
            })
            self.assertEqual(prepared.status_code,200,prepared.content)
            item=prepared.json()
            self.assertEqual(item['count'],1)
            self.assertEqual(item['status'],'draft')
            self.assertIn('لغو 11',item['body'])
            self.assertNotIn('09120001111',str(item))
            self.assertEqual(process_bulk_sms(),0)
            sender.assert_not_called()
            # Wrong explicit phrase and absent consent cannot queue.
            denied=self.post_json({
                'action':'approve','campaign_id':item['id'],'count':1,
                'consent_attested':False,'typed':'تایید',
            })
            self.assertEqual(denied.status_code,400)
            approved=self.post_json({
                'action':'approve','campaign_id':item['id'],'count':1,
                'consent_attested':True,'typed':'تایید',
            })
            self.assertEqual(approved.status_code,200,approved.content)
            self.assertEqual(approved.json()['status'],'queued')
            self.assertEqual(process_bulk_sms(),1)
            sender.assert_called_once()
            recipient=BulkSmsRecipient.objects.get(campaign_id=item['id'])
            self.assertEqual(recipient.status,'accepted')
            self.assertEqual(process_bulk_sms(),0)
            self.assertEqual(self.post_json({
                'action':'approve','campaign_id':item['id'],'count':1,
                'consent_attested':True,'typed':'تایید',
            }).status_code,400)

    def test_pause_resume_and_cancel_are_effective_before_send(self):
        prepared=self.post_json({
            'action':'prepare','segments':['lead_all'],'body':'پیام مجاز گرین لایف',
        }).json()
        self.post_json({'action':'approve','campaign_id':prepared['id'],
            'count':prepared['count'],'consent_attested':True,'typed':'تایید'})
        self.assertEqual(self.post_json({'action':'pause',
            'campaign_id':prepared['id']}).json()['status'],'paused')
        with patch('core.sms.send_sms') as sender:
            self.assertEqual(process_bulk_sms(),0)
            sender.assert_not_called()
            self.assertEqual(self.post_json({'action':'resume',
                'campaign_id':prepared['id']}).json()['status'],'queued')
            self.assertEqual(self.post_json({'action':'cancel',
                'campaign_id':prepared['id']}).json()['status'],'cancelled')
            self.assertEqual(process_bulk_sms(),0)
            sender.assert_not_called()
        self.assertEqual(BulkSmsRecipient.objects.get().status,'skipped')

    def test_reply_11_globally_suppresses_already_queued_and_future_campaigns(self):
        prepared=self.post_json({
            'action':'prepare','segments':['lead_all'],'body':'پیام بازاریابی مجاز',
        }).json()
        self.post_json({'action':'approve','campaign_id':prepared['id'],
            'count':1,'consent_attested':True,'typed':'تایید'})
        reply=self.client.get(reverse('sms_center_callback'),{
            'from':'09120001111','text':'11','to':'02134247',
        })
        self.assertEqual(reply.status_code,200)
        self.assertTrue(BulkSmsOptOut.objects.filter(number='09120001111').exists())
        with patch('core.sms.send_sms') as sender:
            self.assertEqual(process_bulk_sms(),0)
            sender.assert_not_called()
        self.assertEqual(BulkSmsRecipient.objects.get().status,'skipped')
        denied=self.post_json({
            'action':'prepare','segments':['lead_all'],'body':'پیام بازاریابی مجاز',
        })
        self.assertEqual(denied.status_code,400)

    def test_concurrent_repeat_campaign_is_excluded_by_seven_day_cooldown(self):
        first=prepare_campaign(
            user=self.executive,keys=['lead_all'],combine='any',
            date_filter=None,body='پیام تاییدشده',
        )
        approve_campaign(campaign_id=first['id'],user=self.executive,
                         count=1,attested=True,typed='تایید')
        with patch('core.sms.send_sms'):
            self.assertEqual(process_bulk_sms(),1)
        denied=self.post_json({
            'action':'prepare','segments':['lead_all'],'body':'دوباره پیام',
        })
        self.assertEqual(denied.status_code,400)

    def test_ambiguous_gateway_failure_has_no_automatic_retry(self):
        first=prepare_campaign(
            user=self.executive,keys=['lead_all'],combine='any',
            date_filter=None,body='پیام یک بار',
        )
        approve_campaign(campaign_id=first['id'],user=self.executive,
                         count=1,attested=True,typed='تایید')
        with patch('core.sms.send_sms',side_effect=TimeoutError('unclear')) as sender:
            self.assertEqual(process_bulk_sms(),1)
            self.assertEqual(process_bulk_sms(),0)
            sender.assert_called_once()
        self.assertEqual(BulkSmsRecipient.objects.get().status,'failed')

    def test_non_executive_cannot_create_approve_or_see_status(self):
        self.client.force_login(self.staff)
        self.assertEqual(self.post_json({
            'action':'prepare','segments':['lead_all'],'body':'متن پیامک'
        }).status_code,403)
        self.assertEqual(self.client.get(
            reverse('bulk_sms_campaigns_status_api')
        ).status_code,403)

    def test_prepared_draft_expires_and_cannot_be_approved(self):
        draft=prepare_campaign(
            user=self.executive,keys=['lead_all'],combine='any',
            date_filter=None,body='متن تست',
        )
        BulkSmsCampaign.objects.filter(pk=draft['id']).update(
            created_at=timezone.now()-timedelta(hours=2)
        )
        self.assertEqual(self.post_json({
            'action':'approve','campaign_id':draft['id'],'count':1,
            'consent_attested':True,'typed':'تایید',
        }).status_code,400)

    def test_global_daily_limit_prevents_further_sending(self):
        draft=prepare_campaign(
            user=self.executive,keys=['lead_all'],combine='any',
            date_filter=None,body='متن تست',
        )
        approve_campaign(campaign_id=draft['id'],user=self.executive,
                         count=1,attested=True,typed='تایید')
        with patch('core.bulk_sms_dispatch.MAX_DAILY_ATTEMPTS',0):
            with patch('core.sms.send_sms') as sender:
                self.assertEqual(process_bulk_sms(),0)
                sender.assert_not_called()
        self.assertEqual(BulkSmsRecipient.objects.get().status,'pending')
