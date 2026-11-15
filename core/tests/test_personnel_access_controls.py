from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.test import Client, TestCase
from django.urls import reverse

from core.credential_security import change_mobile_pin
from core.models import AuditLog, Branch, EmployeeProfile


class PersonnelAccessControlTests(TestCase):
    def setUp(self):
        self.niavaran=Branch.objects.create(name='نیاوران')
        self.isfahan=Branch.objects.create(name='اصفهان')
        self.admin=User.objects.create_user('manager-control-test',password='AdminTest123',first_name='مدیر')
        EmployeeProfile.objects.update_or_create(user=self.admin,defaults={'role':'admin','branch':self.niavaran})
        self.member=User.objects.create_user('account-to-disable',password='MemberTest123',first_name='کارمند')
        self.profile,_=EmployeeProfile.objects.update_or_create(user=self.member,defaults={'role':'receptionist','branch':self.isfahan})
        self.other=User.objects.create_user('other-staff',password='MemberTest123')
        self.other_profile,_=EmployeeProfile.objects.update_or_create(user=self.other,defaults={'role':'consultant','branch':self.niavaran})
        self.client.force_login(self.admin)

    def test_filters_default_active_and_counts_are_stable(self):
        url=reverse('employee_list')
        response=self.client.get(url)
        self.assertEqual(response.context['status_filter'],'active')
        self.assertContains(response,'?status=inactive')
        self.assertContains(response,'?status=all')
        starting_active=response.context['status_counts']['active']
        self.assertGreaterEqual(starting_active,3)
        self.assertEqual(response.context['status_counts']['inactive'],0)

        self.member.is_active=False
        self.member.save(update_fields=['is_active'])
        response=self.client.get(url)
        self.assertEqual(response.context['status_counts']['inactive'],1)
        self.assertEqual(response.context['status_counts']['active'],starting_active-1)
        self.assertNotContains(response,reverse('employee_file',args=[self.profile.pk]))
        response=self.client.get(url+'?status=inactive')
        self.assertContains(response,reverse('employee_file',args=[self.profile.pk]))
        self.assertNotContains(response,reverse('employee_file',args=[self.other_profile.pk]))
        response=self.client.get(url+'?status=all')
        self.assertContains(response,reverse('employee_file',args=[self.profile.pk]))
        self.assertContains(response,reverse('employee_file',args=[self.other_profile.pk]))

    def test_deactivation_blocks_desktop_mobile_and_revokes_previous_sessions(self):
        url=reverse('employee_status_change',args=[self.profile.pk])
        desktop=Client()
        desktop.force_login(self.member)
        mobile=Client()
        mobile.force_login(self.member)
        desktop_session=desktop.session.session_key
        mobile_session=mobile.session.session_key
        self.assertTrue(Session.objects.filter(session_key=desktop_session).exists())
        self.assertTrue(Session.objects.filter(session_key=mobile_session).exists())
        change_mobile_pin(self.member,'123456')
        response=self.client.post(url,{'action':'deactivate'})
        self.assertRedirects(response,reverse('employee_list')+'?status=inactive')
        self.member.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertFalse(self.profile.is_active)
        self.assertFalse(Session.objects.filter(session_key__in=[desktop_session,mobile_session]).exists())
        self.assertEqual(desktop.get(reverse('employee_list')).status_code,302)
        desk_login=Client().post(reverse('login'),{'username':self.member.username,'password':'MemberTest123'})
        self.assertEqual(desk_login.status_code,200)
        mobile_login=Client().post(
            reverse('login'),{'username':self.member.username,'password':'123456'},
            HTTP_USER_AGENT='Android Mobile',HTTP_SEC_CH_UA_MOBILE='?1',
        )
        self.assertEqual(mobile_login.status_code,200)
        self.assertTrue(AuditLog.objects.filter(
            actor=self.admin,object_id=str(self.member.id),action='personnel_access_disabled',
        ).exists())

    def test_activation_restores_only_this_personnel_account(self):
        self.client.post(reverse('employee_status_change',args=[self.profile.pk]),{'action':'deactivate'})
        response=self.client.post(reverse('employee_status_change',args=[self.profile.pk]),{'action':'activate'})
        self.assertRedirects(response,reverse('employee_list')+'?status=active')
        self.member.refresh_from_db()
        self.profile.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.assertTrue(self.profile.is_active)
        self.assertTrue(User.objects.filter(pk=self.member.pk).exists())

    def test_permission_boundary_no_get_no_other_branch_no_privileged_accounts(self):
        target=reverse('employee_status_change',args=[self.profile.pk])
        self.assertEqual(self.client.get(target).status_code,405)
        self.assertEqual(self.client.post(target,{'action':'arbitrary'}).status_code,400)
        self.assertEqual(
            self.client.post(reverse('employee_status_change',args=[self.admin.profile.pk]),
                             {'action':'deactivate'}).status_code,403
        )
        branch_manager=User.objects.create_user('branch-manager-control',password='AdminTest123')
        EmployeeProfile.objects.update_or_create(user=branch_manager,defaults={'role':'manager','branch':self.niavaran})
        self.client.force_login(branch_manager)
        self.assertEqual(self.client.post(target,{'action':'deactivate'}).status_code,403)
        self.member.refresh_from_db()
        self.assertTrue(self.member.is_active)
        self.client.force_login(self.member)
        self.assertRedirects(
            self.client.post(target,{'action':'deactivate'}),reverse('dashboard')
        )

    def test_old_edit_form_also_revokes_sessions(self):
        active_client=Client()
        active_client.force_login(self.member)
        old_key=active_client.session.session_key
        response=self.client.post(reverse('employee_edit',args=[self.profile.pk]),{
            'first_name':self.member.first_name,'last_name':'تست',
            'username':self.member.username,'email':'',
            'employee_code':'','job_title':'منشی','phone':'',
            'birth_date':'','start_date':'','country':'','preferred_language':'fa',
            'branch':str(self.isfahan.pk),'role':'receptionist','shift_group':'',
            'address':'','education':'','is_insured':'','new_password':'',
        })
        self.assertRedirects(response,reverse('employee_file',args=[self.profile.pk]))
        self.member.refresh_from_db()
        self.assertFalse(self.member.is_active)
        self.assertFalse(Session.objects.filter(session_key=old_key).exists())

    def test_inactive_profile_alone_rejects_login(self):
        self.profile.is_active=False
        self.profile.save(update_fields=['is_active'])
        self.client.logout()
        response=self.client.post(
            reverse('login'),{'username':self.member.username,'password':'MemberTest123'},
        )
        self.assertEqual(response.status_code,200)
        self.assertNotIn('_auth_user_id',self.client.session)

    def test_switch_is_compact_accessible_and_posts_correct_action(self):
        page=self.client.get(reverse('employee_list')+'?status=all')
        self.assertContains(page,'class="personnel-access-switch"')
        self.assertContains(page,'role="switch" aria-checked="true"')
        self.assertContains(page,reverse('employee_status_change',args=[self.profile.pk]))
        self.assertNotContains(page,'class="personnel-access-button"')
        self.client.post(reverse('employee_status_change',args=[self.profile.pk]),{'action':'deactivate'})
        page=self.client.get(reverse('employee_list')+'?status=inactive')
        self.assertContains(page,'role="switch" aria-checked="false"')
        self.assertContains(page,'name="action" value="activate"')
