from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Branch, Country, EmployeeProfile, ReferralLead, ReferralProfile


class CountryWorkspaceTests(TestCase):
    def setUp(self):
        self.iran=Country.objects.get(code='IR')
        self.turkey=Country.objects.get(code='TR')
        self.ir_branch=Branch.objects.create(name='Country Test Tehran',country=self.iran)
        self.tr_branch=Branch.objects.create(name='Country Test Istanbul',country=self.turkey)

        self.admin=User.objects.create_user('country-admin',password='StrongPass123')
        EmployeeProfile.objects.create(
            user=self.admin,role='admin',country=self.iran,branch=self.ir_branch,
            preferred_language='fa',
        )

        self.ir_user=User.objects.create_user('ir-staff',password='StrongPass123',first_name='Iran Staff')
        EmployeeProfile.objects.create(
            user=self.ir_user,role='employee',country=self.iran,branch=self.ir_branch,
            preferred_language='fa',
        )
        self.tr_user=User.objects.create_user('tr-staff',password='StrongPass123',first_name='Turkey Staff')
        EmployeeProfile.objects.create(
            user=self.tr_user,role='employee',country=self.turkey,branch=self.tr_branch,
            preferred_language='tr',
        )

        source_user=User.objects.create_user('country-source',password='StrongPass123')
        self.source=ReferralProfile.objects.create(
            user=source_user,referral_code='GLCOUNTRYTEST',is_active=False,
        )

    def test_admin_defaults_to_own_country_and_can_switch(self):
        self.client.login(username='country-admin',password='StrongPass123')

        response=self.client.get(reverse('employee_list'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'Iran Staff')
        self.assertNotContains(response,'Turkey Staff')

        response=self.client.post(
            reverse('country_switch'),
            {'country':'TR','next':reverse('employee_list')},
        )
        self.assertRedirects(response,reverse('employee_list'))
        self.assertEqual(self.client.session.get('greenlife_country_scope'),'TR')

        response=self.client.get(reverse('employee_list'))
        self.assertContains(response,'Turkey Staff')
        self.assertNotContains(response,'Iran Staff')

    def test_all_country_scope_shows_both_staff_markets(self):
        self.client.login(username='country-admin',password='StrongPass123')
        self.client.post(reverse('country_switch'),{'country':'ALL','next':reverse('employee_list')})
        response=self.client.get(reverse('employee_list'))
        self.assertContains(response,'Iran Staff')
        self.assertContains(response,'Turkey Staff')

    def test_lead_hub_metrics_follow_selected_country(self):
        ReferralLead.objects.create(
            referrer=self.source,country=self.iran,preferred_language='fa',
            full_name='Iran Lead',phone='09121110001',source='link',
        )
        ReferralLead.objects.create(
            referrer=self.source,country=self.turkey,preferred_language='tr',
            full_name='Turkey Lead',phone='+905321110001',source='link',
            notes='[market:turkey]',
        )
        self.client.login(username='country-admin',password='StrongPass123')
        self.client.post(reverse('country_switch'),{'country':'TR','next':reverse('lead_management_dashboard')})
        response=self.client.get(reverse('lead_management_dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['lead_kpis']['total'],1)
        self.assertContains(response,'Turkey Lead')
        self.assertNotContains(response,'Iran Lead')

    def test_regular_staff_cannot_switch_country(self):
        self.client.login(username='ir-staff',password='StrongPass123')
        response=self.client.post(reverse('country_switch'),{'country':'TR','next':'/'})
        self.assertEqual(response.status_code,403)
