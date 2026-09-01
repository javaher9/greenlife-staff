from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Branch, EmployeeProfile, ReferralLead, ReferralProfile, ReferralSale


class ReferralModuleTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='نیاوران')
        self.admin=User.objects.create_user('ref-admin',password='pass',first_name='علی',last_name='جواهریان')
        EmployeeProfile.objects.update_or_create(user=self.admin,defaults={'role':'admin','branch':self.branch,'is_active':True})
        self.staff=User.objects.create_user('ref-staff',password='pass',first_name='مریم',last_name='مرادی')
        EmployeeProfile.objects.update_or_create(user=self.staff,defaults={'role':'employee','branch':self.branch,'is_active':True,'phone':'09120000000'})
        self.client.force_login(self.staff)

    def profile(self,user,sponsor=None,code=None):
        return ReferralProfile.objects.create(
            user=user,sponsor=sponsor,referral_code=code or f'GL{user.pk:08d}',phone='09121111111',created_by=self.admin,
        )

    def member(self,username,sponsor):
        user=User.objects.create_user(username,password='pass',first_name='عضو',last_name=username)
        EmployeeProfile.objects.update_or_create(user=user,defaults={'role':'referrer','branch':self.branch,'is_active':True})
        return self.profile(user,sponsor=sponsor)

    def test_staff_dashboard_creates_root_profile_and_shows_real_sections(self):
        response=self.client.get(reverse('referral_dashboard'))
        self.assertEqual(response.status_code,200)
        profile=ReferralProfile.objects.get(user=self.staff)
        self.assertIsNone(profile.sponsor)
        for label in ('لیدها','اعضای شبکه','فروش موفق','درآمد من','لینک و QR شما'):
            self.assertContains(response,label)

    def test_employee_home_promotes_sales_network_and_uses_distinct_mobile_navigation(self):
        response=self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code,200)
        html=response.content.decode()
        self.assertIn('href="/referrals/" class="gl-quick-card gl-quick-referral"',html)
        self.assertIn('<span>شبکه فروش من</span>',html)
        self.assertIn('employee-profile-nav employee-bottom-nav',html)
        self.assertIn('employee-guidelines-nav employee-bottom-nav',html)
        self.assertNotIn('employee-tasks-nav employee-bottom-nav',html)
        self.assertNotIn('attendance-nav employee-bottom-nav',html)

    def test_admin_gets_management_command_dashboard_not_personal_qr_card(self):
        self.profile(self.staff)
        self.client.force_login(self.admin)
        response=self.client.get(reverse('referral_dashboard'))
        self.assertEqual(response.status_code,200)
        for label in ('مرکز مدیریت معرفی مشتری','قیف تبدیل مشتری','پیگیری‌های سررسیدشده','پورسانت معوق'):
            self.assertContains(response,label)
        self.assertNotContains(response,'لینک و QR شما')

    def test_public_referral_link_uses_external_canonical_domain(self):
        self.profile(self.staff,code='GLCANONICAL')
        response=self.client.get(reverse('referral_dashboard'))
        self.assertContains(response,'https://staff.greenlifeclinics.com/r/GLCANONICAL/')
        self.assertNotContains(response,'http://testserver/r/GLCANONICAL/')

    def test_staff_sales_guide_defines_external_leads_and_protects_company_channels(self):
        response=self.client.get(reverse('referral_guide'))
        self.assertEqual(response.status_code,200)
        for label in (
            'فردی کاملاً جدید از خارج مجموعه','همراهان مراجعه‌کنندگان','روش روزانه ۳-۱-۱',
            'واتساپ رسمی گرین‌لایف','اینستاگرام مجموعه','بانک مشتریان',
        ):
            self.assertContains(response,label)

        guidelines=self.client.get(reverse('my_guidelines'))
        self.assertContains(guidelines,'دستورالعمل رسمی شبکه فروش من')
        self.assertContains(guidelines,'واتساپ رسمی گرین‌لایف')

    def test_network_is_limited_to_two_levels(self):
        root=self.profile(self.staff)
        first=self.member('level-one',root)
        second=self.member('level-two',first)
        user=User.objects.create_user('level-three',password='pass')
        EmployeeProfile.objects.update_or_create(user=user,defaults={'role':'referrer','branch':self.branch,'is_active':True})
        with self.assertRaises(ValidationError):
            self.profile(user,sponsor=second)

    def test_level_two_cannot_create_another_member(self):
        root=self.profile(self.staff)
        first=self.member('one-member',root)
        second=self.member('two-member',first)
        self.client.force_login(second.user)
        response=self.client.get(reverse('referral_member_create'),follow=True)
        self.assertRedirects(response,reverse('referral_network'))
        self.assertContains(response,'امکان ساخت سطح سوم وجود ندارد.')

    def test_referrer_can_create_level_one_account_with_photo_optional(self):
        root=self.profile(self.staff)
        response=self.client.post(reverse('referral_member_create'),{
            'sponsor':root.pk,'first_name':'سارا','last_name':'احمدی','phone':'09123334444',
            'username':'sara-referrer','password':'safe-pass-123',
        })
        self.assertRedirects(response,reverse('referral_network'))
        created=ReferralProfile.objects.get(user__username='sara-referrer')
        self.assertEqual(created.sponsor,root)
        self.assertEqual(created.level,1)
        self.assertEqual(created.user.profile.role,'referrer')

    def test_public_link_records_lead_for_exact_referrer(self):
        root=self.profile(self.staff,code='GLPUBLIC1')
        self.client.logout()
        response=self.client.post(reverse('public_referral_lead',args=[root.referral_code]),{
            'full_name':'مشتری آزمایشی','phone':'09124445555','alternate_phone':'',
            'interested_service':'لاغری موضعی','notes':'تماس عصر','consent':'on',
        })
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'درخواست شما ثبت شد')
        lead=ReferralLead.objects.get()
        self.assertEqual(lead.referrer,root)
        self.assertEqual(lead.source,'link')

    def test_qr_source_is_distinguished_from_normal_link(self):
        root=self.profile(self.staff,code='GLPUBLIC2')
        self.client.logout()
        self.client.post(reverse('public_referral_lead',args=[root.referral_code])+'?src=qr',{
            'full_name':'مشتری QR','phone':'09125556666','alternate_phone':'',
            'interested_service':'کاهش وزن','notes':'','consent':'on',
        })
        self.assertEqual(ReferralLead.objects.get().source,'qr')

    def test_manager_records_sale_and_two_commissions(self):
        root=self.profile(self.staff)
        first=self.member('seller-one',root)
        lead=ReferralLead.objects.create(referrer=first,full_name='مشتری فروش',phone='09127778888')
        self.client.force_login(self.admin)
        response=self.client.post(reverse('referral_sale_edit',args=[lead.pk]),{
            'sale_date':'۱۴۰۵/۰۶/۰۹','amount':'10000000','direct_commission':'1000000',
            'level_two_commission':'250000','status':'approved','note':'تأیید مدیریت',
        })
        self.assertRedirects(response,reverse('referral_sales'))
        sale=ReferralSale.objects.get(lead=lead)
        self.assertEqual(sale.amount,Decimal('10000000'))
        self.assertEqual(sale.direct_commission,Decimal('1000000'))
        self.assertEqual(sale.level_two_commission,Decimal('250000'))
        lead.refresh_from_db(); self.assertEqual(lead.status,'won')

    def test_regular_referrer_cannot_manage_lead_or_export_crm(self):
        root=self.profile(self.staff)
        lead=ReferralLead.objects.create(referrer=root,full_name='مشتری',phone='09128889999')
        response=self.client.get(reverse('referral_lead_manage',args=[lead.pk]))
        self.assertRedirects(response,reverse('referral_dashboard'))
        response=self.client.get(reverse('referral_crm_export'))
        self.assertRedirects(response,reverse('referral_dashboard'))

    def test_admin_exports_excel_compatible_csv_and_stable_crm_json(self):
        root=self.profile(self.staff)
        ReferralLead.objects.create(referrer=root,full_name='خروجی آزمایشی',phone='09129990000')
        self.client.force_login(self.admin)
        csv_response=self.client.get(reverse('referral_export_csv'))
        self.assertEqual(csv_response.status_code,200)
        self.assertTrue(csv_response.content.startswith(b'\xef\xbb\xbf'))
        self.assertIn('text/csv',csv_response['Content-Type'])
        json_response=self.client.get(reverse('referral_crm_export'))
        self.assertEqual(json_response.status_code,200)
        payload=json_response.json()
        self.assertEqual(payload['schema'],'greenlife.referrals.v1')
        self.assertEqual(payload['leads'][0]['phone'],'09129990000')

    def test_external_referrer_login_redirects_to_referral_panel_and_not_personnel(self):
        root=self.profile(self.staff)
        external=self.member('external-login',root)
        self.client.force_login(external.user)
        response=self.client.get(reverse('dashboard'))
        self.assertRedirects(response,reverse('referral_dashboard'))
        self.client.force_login(self.admin)
        personnel=self.client.get(reverse('employee_list'))
        self.assertNotContains(personnel,'external-login')
