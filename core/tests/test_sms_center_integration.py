from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog, Branch, ReferralLead, SmsAutomationRule
from core.sms_automation import schedule_sms_event, validate_template


class SmsCenterIntegrationTests(TestCase):
    def test_exact_reply_classification_creates_leads_only_for_supported_codes(self):
        for code in ('20','5','6','7','8','9'):
            phone=f'091200000{int(code):02d}'[-11:]
            response=self.client.get(reverse('sms_center_callback'),{
                'from':phone,'to':'3000','text':code,'time':'2026-10-05 12:00',
            })
            self.assertEqual(response.status_code,200)
            self.assertTrue(ReferralLead.objects.filter(phone=phone).exists())
        before=ReferralLead.objects.count()
        for code in ('11','10','120','205'):
            self.client.get(reverse('sms_center_callback'),{
                'from':'09129999999','to':'3000','text':code,'time':'now',
            })
        self.assertEqual(ReferralLead.objects.count(),before)
        self.assertEqual(AuditLog.objects.filter(action='sms_center_reply').count(),10)

    def test_whitespace_is_normalized_but_matching_stays_exact(self):
        self.client.get(reverse('sms_center_callback'),{
            'from':'09121111111','to':'3000','text':'  20  ','time':'now',
        })
        self.assertTrue(ReferralLead.objects.filter(phone='09121111111').exists())
        self.client.get(reverse('sms_center_callback'),{
            'from':'09122222222','to':'3000','text':'120','time':'now',
        })
        row=AuditLog.objects.filter(action='sms_center_reply').latest('id')
        self.assertEqual(row.metadata['category'],'other')

    def test_sms_management_exposes_callback_and_all_events_are_connected(self):
        admin=User.objects.create_superuser('sms-admin','sms@example.com','x')
        self.client.force_login(admin)
        response=self.client.get(reverse('sms_management'))
        self.assertContains(response,'%%address%%')
        self.assertContains(response,reverse('sms_leads'))
        self.assertNotContains(response,'در انتظار اتصال')

    def test_appointment_address_variable_is_valid_and_resolved(self):
        self.assertIn('address',validate_template('آدرس: {address}'))
        rule=SmsAutomationRule.objects.create(
            event='appointment_booked',is_enabled=True,recipient='patient',
            message_template='آدرس: {address}',
        )
        item=schedule_sms_event('appointment_booked','address-test',patient_number='09121234567',context={'address':'تهران، نیاوران'})
        self.assertIsNotNone(item)
        self.assertEqual(item.body,'آدرس: تهران، نیاوران')
