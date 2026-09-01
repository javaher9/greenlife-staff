from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.forms import ReferralLeadManageForm
from core.models import Branch, EmployeeProfile, ReferralLead, ReferralProfile, StaffNotification, Task
from core.referral_views import _auto_assign_call_center


class CallCenterRoleTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='کال‌سنتر')
        self.operator_one=self.make_user('operator-one','call_center','نرگس')
        self.operator_two=self.make_user('operator-two','call_center','بنفشه')
        self.staff=self.make_user('staff','employee','کارمند')
        self.referrer_user=self.make_user('referrer-root','employee','معرف')
        self.referrer=ReferralProfile.objects.create(
            user=self.referrer_user,referral_code='GLTESTROOT',created_by=self.referrer_user,
        )
        self.lead_one=ReferralLead.objects.create(
            referrer=self.referrer,full_name='مشتری اول',phone='09120000001',
            interested_service='لاغری',assigned_to=self.operator_one.profile,
        )
        self.lead_two=ReferralLead.objects.create(
            referrer=self.referrer,full_name='مشتری دوم',phone='09120000002',
            assigned_to=self.operator_two.profile,
        )
        self.client.force_login(self.operator_one)

    def make_user(self,username,role,first_name):
        user=User.objects.create_user(username,password='pass',first_name=first_name)
        EmployeeProfile.objects.update_or_create(
            user=user,defaults={
                'role':role,'branch':self.branch,'job_title':'کارشناس کال‌سنتر' if role=='call_center' else '',
                'is_active':True,
            },
        )
        return User.objects.get(pk=user.pk)

    def test_role_has_distinct_label_and_dashboard_redirect(self):
        self.assertIn(('call_center','کال‌سنتر'),EmployeeProfile.ROLE_CHOICES)
        response=self.client.get(reverse('dashboard'))
        self.assertRedirects(response,reverse('call_center_dashboard'),fetch_redirect_response=False)

    def test_dashboard_only_shows_assigned_leads_and_direct_call(self):
        response=self.client.get(reverse('call_center_dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'مشتری اول')
        self.assertContains(response,'tel:09120000001')
        self.assertNotContains(response,'مشتری دوم')
        self.assertNotContains(response,'شبکه فروش من')
        self.assertNotContains(response,'/referrals/')

    def test_operator_can_record_result_only_for_own_lead(self):
        response=self.client.post(reverse('call_center_lead',args=[self.lead_one.pk]),{
            'status':'contacted','next_follow_up':'','interested_service':'لاغری موضعی',
            'notes':'تماس انجام شد؛ عصر دوباره پیگیری شود.',
        })
        self.assertRedirects(response,reverse('call_center_dashboard'))
        self.lead_one.refresh_from_db()
        self.assertEqual(self.lead_one.status,'contacted')
        self.assertIn('تماس انجام شد',self.lead_one.notes)
        denied=self.client.get(reverse('call_center_lead',args=[self.lead_two.pk]))
        self.assertEqual(denied.status_code,404)

    def test_network_sales_and_referral_dashboard_are_blocked(self):
        for name in ('referral_dashboard','referral_network','referral_sales','referral_guide'):
            self.assertEqual(self.client.get(reverse(name)).status_code,403)
        self.assertFalse(ReferralProfile.objects.filter(user=self.operator_one).exists())

    def test_new_leads_are_balanced_between_active_operators(self):
        extra=ReferralLead.objects.create(
            referrer=self.referrer,full_name='صف اضافه',phone='09120000003',
            assigned_to=self.operator_one.profile,
        )
        self.assertIsNotNone(extra.pk)
        new_lead=ReferralLead.objects.create(
            referrer=self.referrer,full_name='مشتری تازه',phone='09120000004',
        )
        assigned=_auto_assign_call_center(new_lead)
        new_lead.refresh_from_db()
        self.assertEqual(assigned,self.operator_two.profile)
        self.assertEqual(new_lead.assigned_to,self.operator_two.profile)
        self.assertTrue(StaffNotification.objects.filter(
            user=self.operator_two,notification_type='call_center_lead',
        ).exists())

    def test_manager_assignment_field_only_lists_call_center_staff(self):
        form=ReferralLeadManageForm(instance=self.lead_one)
        profiles=list(form.fields['assigned_to'].queryset)
        self.assertIn(self.operator_one.profile,profiles)
        self.assertIn(self.operator_two.profile,profiles)
        self.assertNotIn(self.staff.profile,profiles)

    def test_regular_staff_pages_remain_scoped_to_operator(self):
        own=Task.objects.create(title='تماس با مشتری',assigned_to=self.operator_one,created_by=self.staff)
        other=Task.objects.create(title='وظیفه شخص دیگر',assigned_to=self.staff,created_by=self.staff)
        response=self.client.get(reverse('task_list'))
        self.assertContains(response,own.title)
        self.assertNotContains(response,other.title)
