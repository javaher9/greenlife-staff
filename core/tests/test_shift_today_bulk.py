from datetime import time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Branch, EmployeeProfile, ShiftAssignment


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
        return user

    def test_internal_manager_sees_personnel_from_all_branches(self):
        self.client.force_login(self.internal)
        response=self.client.get(reverse('shift_today_bulk'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,self.employee.first_name)
        self.assertContains(response,self.other_employee.first_name)
        self.assertNotContains(response,self.admin.first_name)

    def test_bulk_save_creates_only_today_override_for_selected_staff(self):
        self.client.force_login(self.internal)
        response=self.client.post(reverse('shift_today_bulk'),{
            'selected':[str(self.employee.pk)],
            f'start_{self.employee.pk}':'08:30',
            f'end_{self.employee.pk}':'16:30',
        })
        self.assertRedirects(response,reverse('shift_today_bulk'))
        assignment=ShiftAssignment.objects.get(user=self.employee,date=timezone.localdate())
        self.assertEqual(assignment.shift.start_time,time(8,30))
        self.assertEqual(assignment.shift.end_time,time(16,30))
        self.assertFalse(ShiftAssignment.objects.filter(user=self.other_employee,date=timezone.localdate()).exists())

    def test_internal_manager_cannot_assign_management_account(self):
        self.client.force_login(self.internal)
        response=self.client.post(reverse('shift_today_bulk'),{
            'selected':[str(self.admin.pk)],
            f'start_{self.admin.pk}':'08:00',f'end_{self.admin.pk}':'17:00',
        })
        self.assertEqual(response.status_code,200)
        self.assertFalse(ShiftAssignment.objects.filter(user=self.admin,date=timezone.localdate()).exists())

    def test_regular_employee_is_denied(self):
        self.client.force_login(self.employee)
        response=self.client.get(reverse('shift_today_bulk'))
        self.assertRedirects(response,reverse('dashboard'))
