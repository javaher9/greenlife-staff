from unittest.mock import patch
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from core.models import EmployeeProfile, ReferralLead, SmsMessageLog, Country


class StaffMarketingSmsTests(TestCase):
    def setUp(self):
        self.user=User.objects.create_user('sms-staff-sample',password='test-only')
        EmployeeProfile.objects.update_or_create(
            user=self.user,defaults={'role':'employee','is_active':True,'can_send_marketing_sms':True},
        )
        self.client.force_login(self.user)

    def test_disabled_user_is_denied(self):
        EmployeeProfile.objects.filter(user=self.user).update(can_send_marketing_sms=False)
        self.assertEqual(self.client.get(reverse('marketing_sms_compose')).status_code,403)

    def test_enabled_staff_has_page(self):
        response=self.client.get(reverse('marketing_sms_compose'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'ارسال پیامک')

    @patch('core.marketing_sms_views.send_sms')
    @patch('core.marketing_sms_views.ApiServerSettings.load')
    def test_manual_sms_uses_service_and_actor(self,config,send):
        config.return_value.is_enabled=True
        config.return_value.is_configured=True
        response=self.client.post(reverse('marketing_sms_compose'),{
            'mode':'manual','numbers':'09121112233','body':'پیام تست',
        })
        self.assertRedirects(response,reverse('marketing_sms_compose'))
        send.assert_called_once_with('09121112233','پیام تست',
                                     created_by=self.user,purpose='manual')

    @patch('core.marketing_sms_views.send_sms')
    @patch('core.marketing_sms_views.ApiServerSettings.load')
    def test_selected_iran_lead_sms(self,config,send):
        config.return_value.is_enabled=True
        config.return_value.is_configured=True
        country=Country.objects.get(code='IR')
        lead=ReferralLead.objects.create(full_name='آزمایشی',phone='09121112233',country=country)
        response=self.client.post(reverse('marketing_sms_compose'),{
            'mode':'selected','source':'leads','selected_ids':[str(lead.pk)],'body':'تست لید',
        })
        self.assertEqual(response.status_code,302)
        send.assert_called_once()

    def test_more_than_25_manual_numbers_rejected(self):
        numbers='\\n'.join(f'0912{i:07d}' for i in range(26))
        response=self.client.post(reverse('marketing_sms_compose'),{
            'mode':'manual','numbers':numbers,'body':'test',
        })
        self.assertEqual(response.status_code,302)
