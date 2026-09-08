from datetime import time, timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Branch, BranchWorkSchedule, EmployeeProfile, EmployeeWorkSchedule, ShiftAssignment
from core.operations import report_required, shift_rule


class ShiftTodayBulkTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='نیاوران',work_start=time(9),work_end=time(17))
        self.other_branch=Branch.objects.create(name='پونک',work_start=time(10),work_end=time(18))
        self.internal=self.make_user('internal','internal_manager',self.branch)
        self.admin=self.make_user('admin-user','admin',self.branch)
        self.employee=self.make_user('employee','employee',self.branch)
        self.other_employee=self.make_user('other-employee','employee',self.other_branch)

    def make_user(self,username,role,branch):
        user=User.objects.create_user(username,password='pass',first_name=username)
        EmployeeProfile.objects.update_or_create(
            user=user,defaults={'role':role,'branch':branch,'is_active':True},
        )
        user.refresh_from_db()
        return user

    def test_internal_manager_can_switch_branch_without_mixing_personnel(self):
        self.client.force_login(self.internal)
        response=self.client.get(reverse('shift_today_bulk'),{'branch':self.branch.pk})
        self.assertEqual(response.status_code,200)
        self.assertEqual([row['user'].pk for row in response.context['rows']],[self.employee.pk])
        response=self.client.get(reverse('shift_today_bulk'),{'branch':self.other_branch.pk})
        self.assertEqual([row['user'].pk for row in response.context['rows']],[self.other_employee.pk])

    def test_bulk_save_creates_only_today_override_for_selected_staff(self):
        self.client.force_login(self.internal)
        response=self.client.post(reverse('shift_today_bulk'),{
            'branch':str(self.branch.pk),'action':'save_today',
            'selected':[str(self.employee.pk)],
            f'start_{self.employee.pk}':'08:30',
            f'end_{self.employee.pk}':'16:30',
        })
        self.assertEqual(response.status_code,302)
        self.assertEqual(response.url,f'/shifts/today/?branch={self.branch.pk}')
        assignment=ShiftAssignment.objects.get(user=self.employee,date=timezone.localdate())
        self.assertEqual(assignment.shift.start_time,time(8,30))
        self.assertEqual(assignment.shift.end_time,time(16,30))
        self.assertFalse(ShiftAssignment.objects.filter(user=self.other_employee,date=timezone.localdate()).exists())

    def test_weekly_screen_renders_branch_and_employee_controls(self):
        self.client.force_login(self.internal)
        response=self.client.get(reverse('shift_today_bulk'),{'mode':'weekly','branch':self.branch.pk})
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'برنامه هفتگی شعبه')
        self.assertContains(response,'تغییر برنامه یک پرسنل')

    def test_internal_manager_cannot_assign_management_account(self):
        self.client.force_login(self.internal)
        response=self.client.post(reverse('shift_today_bulk'),{
            'branch':str(self.branch.pk),'action':'save_today',
            'selected':[str(self.admin.pk)],
            f'start_{self.admin.pk}':'08:00',f'end_{self.admin.pk}':'17:00',
        })
        self.assertEqual(response.status_code,200)
        self.assertFalse(ShiftAssignment.objects.filter(user=self.admin,date=timezone.localdate()).exists())

    def weekly_payload(self,prefix,branch,employee=None):
        data={'branch':str(branch.pk),'action':f'save_{prefix}_weekly'}
        if employee: data['employee']=str(employee.pk)
        for weekday in range(7):
            if weekday!=4:
                data[f'{prefix}_working_{weekday}']='1'
                data[f'{prefix}_start_{weekday}']='09:00'
                data[f'{prefix}_end_{weekday}']='17:00'
        return data

    def test_branch_weekly_schedule_marks_friday_off_without_changing_history(self):
        self.client.force_login(self.internal)
        today=timezone.localdate()
        response=self.client.post(reverse('shift_today_bulk'),self.weekly_payload('branch',self.branch))
        self.assertEqual(response.status_code,302)
        self.assertEqual(BranchWorkSchedule.objects.filter(branch=self.branch).count(),7)
        days_until_friday=(4-today.weekday())%7
        friday=today+timedelta(days=days_until_friday)
        rule=shift_rule(self.employee,friday)
        self.assertTrue(rule['is_off'])
        self.assertFalse(report_required(self.employee,friday))
        historical=shift_rule(self.employee,today-timedelta(days=7))
        self.assertEqual(historical['source'],'branch')

    def test_employee_weekly_rule_overrides_branch_day_off(self):
        today=timezone.localdate()
        BranchWorkSchedule.objects.create(
            branch=self.branch,weekday=4,is_working=False,effective_from=today,
        )
        self.client.force_login(self.internal)
        data=self.weekly_payload('employee',self.branch,self.employee)
        data['employee_working_4']='1'
        data['employee_start_4']='10:00'
        data['employee_end_4']='14:00'
        response=self.client.post(reverse('shift_today_bulk'),data)
        self.assertEqual(response.status_code,302)
        self.assertEqual(EmployeeWorkSchedule.objects.filter(user=self.employee).count(),7)
        friday=today+timedelta(days=(4-today.weekday())%7)
        rule=shift_rule(self.employee,friday)
        self.assertEqual(rule['source'],'employee_weekly')
        self.assertEqual(rule['start'],time(10))
        self.assertFalse(rule['is_off'])

    def test_regular_employee_is_denied(self):
        self.client.force_login(self.employee)
        response=self.client.get(reverse('shift_today_bulk'))
        self.assertRedirects(response,reverse('dashboard'))
