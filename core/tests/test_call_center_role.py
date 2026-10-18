from core.tests.test_internal_messaging import InternalMessagingTests as InternalMessagingRegressionTests
from core.tests.test_appointments import SharedAppointmentTests as SharedAppointmentRegressionTests
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.forms import ReferralLeadManageForm
from core.models import Attendance, Branch, CallCenterLeadGroup, EmployeeProfile, ReferralLead, ReferralProfile, StaffNotification, Task
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
        now=timezone.now(); today=timezone.localdate()
        for operator in (self.operator_one,self.operator_two):
            Attendance.objects.create(
                user=operator,date=today,branch=self.branch,
                check_in=now,status='present',
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

    def test_personal_and_instagram_dm_buttons_have_distinct_destinations(self):
        response=self.client.get(reverse('call_center_dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'href="'+reverse('call_center_direct_lead_create')+'"')
        self.assertContains(response,'href="'+reverse('instagram_manual_lead')+'"')
        dm=self.client.get(reverse('instagram_manual_lead'))
        self.assertEqual(dm.status_code,200)
        self.assertTemplateUsed(dm,'core/instagram_manual_lead.html')

    def test_role_has_distinct_label_and_dashboard_redirect(self):
        self.assertIn(('call_center','کال‌سنتر'),EmployeeProfile.ROLE_CHOICES)
        response=self.client.get(reverse('dashboard'))
        self.assertRedirects(response,reverse('call_center_dashboard'),fetch_redirect_response=False)

    def test_mobile_call_center_uses_personal_dashboard(self):
        response=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Mobile Safari/537.36',
            HTTP_SEC_CH_UA_MOBILE='?1',
        )
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,'core/dashboard.html')
        self.assertContains(response,'cc-mobile-home')
        self.assertNotContains(response,'cc-mobile-leads')
        self.assertContains(response,'cc-mobile-attendance')
        self.assertContains(response,'cc-mobile-tasks')
        self.assertContains(response,'cc-mobile-reports')
        self.assertContains(response,'cc-mobile-notifications')

    def test_dashboard_only_shows_assigned_leads_and_direct_call(self):
        response=self.client.get(reverse('call_center_dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'مشتری اول')
        self.assertContains(response,'tel:09120000001')
        self.assertNotContains(response,'مشتری دوم')
        self.assertNotContains(response,'شبکه فروش من')
        self.assertNotContains(response,'/referrals/')

    def test_dashboard_keeps_mobile_navigation_and_real_work_queue(self):
        response=self.client.get(reverse('call_center_dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'cc-mobile-home')
        self.assertContains(response,'cc-mobile-notifications')
        self.assertContains(response,'class="ccx"')
        self.assertContains(response,'صف کار امروز')
        self.assertContains(response,'data-lead-id="%s"' % self.lead_one.pk)
        self.assertNotContains(response,'data-lead-id="%s"' % self.lead_two.pk)
        self.assertContains(response,'میز کار')
        self.assertContains(response,'عملکرد من')
        self.assertContains(response,'ccx-queue')
        self.assertContains(response,'tel:09120000001')

    def test_quick_message_sends_to_staff_and_creates_notification(self):
        response=self.client.post(reverse('call_center_quick_message'),{
            'recipient':str(self.staff.pk),
            'body':'لطفاً این مراجعه‌کننده را پیگیری کنید',
        })
        self.assertEqual(response.status_code,200)
        payload=response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['message']['recipient'],self.staff.get_full_name() or self.staff.username)
        self.assertTrue(StaffNotification.objects.filter(
            user=self.staff,notification_type='internal_message',
        ).exists())

    def test_quick_message_rejects_external_referrer_recipient(self):
        external=self.make_user('external-referrer','referrer','معرف بیرونی')
        response=self.client.post(reverse('call_center_quick_message'),{
            'recipient':str(external.pk),
            'body':'نباید ارسال شود',
        })
        self.assertEqual(response.status_code,400)
        self.assertFalse(response.json()['ok'])

    def test_operator_can_record_result_only_for_own_lead(self):
        response=self.client.post(reverse('call_center_lead',args=[self.lead_one.pk]),{
            'contact_result':'no_answer','next_follow_up':'','interested_service':'لاغری موضعی',
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

    def test_new_leads_keep_existing_ownership_and_pending_queue_policy(self):
        """The routing worker, not registration itself, settles opening queues."""
        from unittest.mock import patch
        already_owned=ReferralLead.objects.create(
            referrer=self.referrer,full_name='صف اضافه',phone='09120000003',
            assigned_to=self.operator_one.profile,
        )
        new_lead=ReferralLead.objects.create(
            referrer=self.referrer,full_name='مشتری تازه',phone='09120000004',
        )
        with patch('core.lead_routing.release_pending_leads_if_ready',return_value=0), \
             patch('core.lead_routing._live_assignment_allowed',return_value=False):
            self.assertEqual(_auto_assign_call_center(already_owned),self.operator_one.profile)
            self.assertIsNone(_auto_assign_call_center(new_lead))
        new_lead.refresh_from_db()
        self.assertIsNone(new_lead.assigned_to)
        self.assertFalse(StaffNotification.objects.filter(
            user=self.operator_two,notification_type='call_center_lead',
        ).exists())

    def test_groups_are_global_and_existing_leads_go_to_staff_sales_group(self):
        response=self.client.get(reverse('call_center_dashboard'))
        self.assertEqual(response.status_code,200)
        groups=CallCenterLeadGroup.objects.filter(owner__isnull=True)
        names=set(groups.values_list('name',flat=True))
        self.assertTrue({
            'شبکه فروش پرسنل','وب‌سایت','کمپ','شرکت‌ها و همکاری سازمانی','اینستاگرام'
        }.issubset(names))
        self.lead_one.refresh_from_db()
        self.assertEqual(self.lead_one.group.name,'شبکه فروش پرسنل')
        self.assertContains(response,'شبکه فروش پرسنل')

    def test_authorized_operator_can_create_global_group_and_move_own_lead(self):
        self.operator_one.profile.can_manage_call_center_groups=True
        self.operator_one.profile.save(update_fields=['can_manage_call_center_groups'])
        response=self.client.post(reverse('call_center_group_create'),{'name':'کمپ VIP'})
        self.assertRedirects(response,
                             reverse('call_center_dashboard')+'?group='+str(
                                 CallCenterLeadGroup.objects.get(name='کمپ VIP').pk),
                             fetch_redirect_response=False)
        group=CallCenterLeadGroup.objects.get(owner__isnull=True,name='کمپ VIP')
        response=self.client.post(reverse('call_center_lead',args=[self.lead_one.pk]),{
            'contact_result':'no_answer','group':group.pk,'next_follow_up':'',
            'interested_service':'لاغری','notes':'انتقال به گروه کمپ',
        })
        self.assertRedirects(response,reverse('call_center_dashboard'))
        self.lead_one.refresh_from_db()
        self.assertEqual(self.lead_one.group,group)

    def test_operator_can_register_phone_directly_in_own_group(self):
        group=CallCenterLeadGroup.objects.create(owner=self.operator_one.profile,name='پیگیری نمایشگاه')
        response=self.client.post(reverse('call_center_lead_create'),{
            'full_name':'مشتری نمایشگاه','phone':'0912 333 4455','group':group.pk,
            'interested_service':'پوست','notes':'تماس عصر',
        })
        lead=ReferralLead.objects.get(full_name='مشتری نمایشگاه')
        self.assertRedirects(
            response,f"{reverse('call_center_dashboard')}?group={group.pk}",
            fetch_redirect_response=False,
        )
        self.assertEqual(lead.phone,'09123334455')
        self.assertEqual(lead.group,group)
        self.assertEqual(lead.assigned_to,self.operator_one.profile)
        self.assertEqual(lead.created_by,self.operator_one)
        self.assertFalse(lead.referrer.is_active)

    def test_operator_can_use_shared_group_but_lead_stays_with_registrar(self):
        shared_group=CallCenterLeadGroup.objects.create(owner=None,name='کمپ مشترک')
        response=self.client.post(reverse('call_center_lead_create'),{
            'full_name':'لید مشترک','phone':'09124445566','group':shared_group.pk,
            'interested_service':'','notes':'',
        })
        self.assertRedirects(response,
                             reverse('call_center_dashboard')+'?group='+str(shared_group.pk),
                             fetch_redirect_response=False)
        lead=ReferralLead.objects.get(phone='09124445566')
        self.assertEqual(lead.assigned_to,self.operator_one.profile)
        self.assertEqual(lead.group,shared_group)

    def test_referral_registration_retains_lead_even_during_morning_queue(self):
        """Registration remains visible even if round-robin is deferred to 10:15."""
        from unittest.mock import patch
        self.client.force_login(self.referrer_user)
        with patch('core.referral_views._auto_assign_call_center',return_value=None):
            response=self.client.post(reverse('referral_lead_create'),{
                'full_name':'مشتری شفاف','phone':'09121112222',
                'alternate_phone':'','interested_service':'مشاوره','notes':'',
                'referrer':self.referrer.pk,
            },follow=True)
        lead=ReferralLead.objects.get(full_name='مشتری شفاف')
        self.assertEqual(lead.referrer,self.referrer)
        self.assertIsNone(lead.assigned_to)
        self.assertEqual(lead.status,'new')
        self.assertEqual(response.status_code,200)

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
