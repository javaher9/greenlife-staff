from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    ApiServerSettings, Branch, EmployeeProfile,
    ReferralProfile, SmsAutomationRule, SmsScheduledMessage,
)


class NetworkMemberWelcomeSmsTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='Test Welcome Niyavaran')
        self.admin=User.objects.create_user(
            username='welcome-admin',password='Pass1234',
            first_name='علی',last_name='مدیر',
        )
        EmployeeProfile.objects.update_or_create(
            user=self.admin,defaults={'role':'admin','branch':self.branch,'is_active':True},
        )
        self.root=ReferralProfile.objects.create(
            user=self.admin,referral_code='GLWELCOMEADMIN',phone='09121111111',
            created_by=self.admin,
        )
        self.client.force_login(self.admin)
        config=ApiServerSettings.load()
        config.is_enabled=True
        config.api_key_cipher='test-placeholder-key-not-used'
        config.save()
        SmsAutomationRule.objects.update_or_create(
            event='network_member_joined',
            defaults={'is_enabled':True,'recipient':'patient','timing':'immediate',
                      'message_template':'سلام {name}، نام کاربری: {username}، رمز: {password}، لینک ورود: {login_url}'},
        )

    def join(self,username='new-driver',phone='09123334444'):
        return self.client.post(reverse('referral_member_create'),{
            'sponsor':self.root.pk,'first_name':'رضا','last_name':'راننده',
            'phone':phone,'username':username,'password':'NeverSmsMyPassword123',
        })

    def test_internal_signup_enqueues_login_link_without_password(self):
        response=self.join()
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'صف ارسال')
        member=ReferralProfile.objects.get(user__username='new-driver')
        self.assertEqual(member.user.profile.role,'referrer')
        self.assertNotContains(self.client.get(reverse('employee_list')),'رضا راننده')
        item=SmsScheduledMessage.objects.get(
            event_key=f'network_member_joined:referral-{member.pk}:patient'
        )
        self.assertEqual(item.status,'pending')
        self.assertEqual(item.number,'09123334444')
        self.assertIn('https://staff.greenlifeclinics.com/login/',item.body)
        self.assertIn('new-driver',item.body)
        self.assertIn('NeverSmsMyPassword123',item.body)

    def test_disabled_gateway_never_queues_and_still_creates_account(self):
        config=ApiServerSettings.load()
        config.is_enabled=False
        config.save()
        response=self.join()
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'سرویس پیامک هنوز فعال')
        self.assertTrue(ReferralProfile.objects.filter(user__username='new-driver').exists())
        self.assertFalse(SmsScheduledMessage.objects.exists())

    def test_manager_can_resend_login_link_for_existing_member(self):
        self.join()
        member=ReferralProfile.objects.get(user__username='new-driver')
        link=reverse('referral_member_sms_resend',args=[member.pk])
        again=self.client.post(link)
        self.assertRedirects(again,reverse('referral_network'))
        self.assertEqual(SmsScheduledMessage.objects.count(),1)
        SmsScheduledMessage.objects.update(
            status='accepted',created_at=timezone.now()-timedelta(minutes=6),
        )
        resent=self.client.post(link)
        self.assertRedirects(resent,reverse('referral_network'))
        self.assertEqual(SmsScheduledMessage.objects.count(),2)

    def test_non_manager_cannot_resend_sms(self):
        self.join()
        member=ReferralProfile.objects.get(user__username='new-driver')
        normal=User.objects.create_user('ordinary-salesperson',password='Pass1234')
        EmployeeProfile.objects.update_or_create(
            user=normal,defaults={'role':'employee','branch':self.branch,'is_active':True},
        )
        self.client.force_login(normal)
        response=self.client.post(reverse('referral_member_sms_resend',args=[member.pk]))
        self.assertEqual(response.status_code,403)
        self.assertEqual(SmsScheduledMessage.objects.count(),1)

    def test_new_member_creation_is_not_blocked_by_sms_queue_error(self):
        from unittest.mock import patch
        with patch('core.sms_automation.queue_network_welcome_sms',side_effect=RuntimeError('gateway unavailable')):
            response=self.join()
        self.assertEqual(response.status_code,200)
        self.assertTrue(ReferralProfile.objects.filter(user__username='new-driver').exists())
        self.assertContains(response,'وضعیت ارسال خودکار تأیید نشده')

    def test_manager_edits_member_details_and_password_and_queues_new_sms(self):
        self.join()
        member=ReferralProfile.objects.get(user__username='new-driver')
        url=reverse('referral_member_edit',args=[member.pk])
        response=self.client.post(url,{
            'first_name':'حسین','last_name':'راننده','phone':'09127778899',
            'username':'edited-driver','new_password':'NewStrongPassword123',
        })
        self.assertRedirects(response,reverse('referral_network'))
        member.refresh_from_db()
        member.user.refresh_from_db()
        self.assertEqual(member.phone,'09127778899')
        self.assertEqual(member.user.username,'edited-driver')
        self.assertTrue(member.user.check_password('NewStrongPassword123'))
        self.assertEqual(SmsScheduledMessage.objects.filter(status='pending').count(),1)
        item=SmsScheduledMessage.objects.get(status='pending')
        self.assertIn('NewStrongPassword123',item.body)
        self.assertEqual(item.number,'09127778899')

    def test_non_manager_cannot_edit_member(self):
        self.join()
        member=ReferralProfile.objects.get(user__username='new-driver')
        normal=User.objects.create_user('ordinary-editor',password='Pass1234')
        EmployeeProfile.objects.update_or_create(
            user=normal,defaults={'role':'employee','branch':self.branch,'is_active':True},
        )
        self.client.force_login(normal)
        response=self.client.post(reverse('referral_member_edit',args=[member.pk]),{
            'first_name':'Hacked','last_name':'User','phone':'09129998877',
            'username':'hacked','new_password':'FakePassword123',
        })
        self.assertEqual(response.status_code,403)
        member.user.refresh_from_db()
        self.assertEqual(member.user.username,'new-driver')
