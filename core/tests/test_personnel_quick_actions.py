from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.jalali import format_jalali
from core.models import (
    Attendance,
    Branch,
    DailyReport,
    EmployeeProfile,
    PersonnelAction,
    Task,
)


class PersonnelQuickActionTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='نیاوران')
        self.other_branch=Branch.objects.create(name='پونک')
        self.admin=User.objects.create_user('admin-test',password='pass')
        EmployeeProfile.objects.update_or_create(
            user=self.admin,defaults={'role':'admin','is_active':True}
        )
        self.employee_user=User.objects.create_user(
            'employee-test',password='pass',first_name='کارمند',last_name='آزمایشی'
        )
        self.employee=EmployeeProfile.objects.update_or_create(
            user=self.employee_user,
            defaults={'role':'employee','branch':self.branch,'is_active':True},
        )[0]
        self.other_user=User.objects.create_user('other-employee',password='pass')
        self.other_employee=EmployeeProfile.objects.update_or_create(
            user=self.other_user,
            defaults={'role':'employee','branch':self.other_branch,'is_active':True},
        )[0]
        self.client.force_login(self.admin)

    def test_personnel_card_has_all_six_real_actions(self):
        response=self.client.get(reverse('employee_list'))
        self.assertContains(response,reverse('employee_file',args=[self.employee.pk]))
        self.assertContains(response,reverse('employee_reports',args=[self.employee.pk]))
        self.assertContains(response,reverse('employee_attendance',args=[self.employee.pk]))
        self.assertContains(response,reverse('employee_task_create',args=[self.employee.pk]))
        self.assertContains(response,reverse('personnel_action_add',args=[self.employee.pk]))
        self.assertContains(response,reverse('employee_360',args=[self.employee.pk]))
        for label in ('پرونده','گزارش‌ها','حضور','وظیفه','اقدام','عملکرد'):
            self.assertContains(response,f'>{label}</a>')

    def test_employee_reports_are_scoped_to_selected_employee(self):
        selected=DailyReport.objects.create(user=self.employee_user,branch=self.branch,text='گزارش انتخاب‌شده')
        DailyReport.objects.create(user=self.other_user,branch=self.other_branch,text='گزارش فرد دیگر')
        response=self.client.get(reverse('employee_reports',args=[self.employee.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(list(response.context['reports']),[selected])
        self.assertContains(response,'گزارش‌های کارمند آزمایشی')
        self.assertNotContains(response,'گزارش فرد دیگر')

    def test_new_task_is_locked_to_selected_employee(self):
        url=reverse('employee_task_create',args=[self.employee.pk])
        response=self.client.get(url)
        self.assertEqual(response.status_code,200)
        self.assertNotIn('assigned_to',response.context['form'].fields)
        response=self.client.post(url,{
            'title':'پیگیری پرونده مشتری',
            'description':'تا پایان روز نتیجه اعلام شود.',
            'due_date':'',
            'priority':'high',
        })
        self.assertRedirects(response,reverse('employee_file',args=[self.employee.pk]))
        task=Task.objects.get(title='پیگیری پرونده مشتری')
        self.assertEqual(task.assigned_to,self.employee_user)
        self.assertEqual(task.created_by,self.admin)

    def test_management_note_is_saved_for_selected_employee(self):
        url=reverse('personnel_action_add',args=[self.employee.pk])
        response=self.client.post(url,{
            'action_type':'note',
            'title':'یادداشت جلسه',
            'description':'موضوع در جلسه بعدی پیگیری شود.',
            'event_date':format_jalali(timezone.localdate()),
        })
        self.assertRedirects(response,reverse('employee_360',args=[self.employee.pk]))
        action=PersonnelAction.objects.get(title='یادداشت جلسه')
        self.assertEqual(action.user,self.employee_user)
        self.assertEqual(action.created_by,self.admin)
        self.assertEqual(action.action_type,'note')

    def test_attendance_page_only_shows_selected_employee_history(self):
        now=timezone.now()
        Attendance.objects.create(
            user=self.employee_user,branch=self.branch,date=timezone.localdate(),
            check_in=now-timedelta(hours=8),check_out=now,status='present',
        )
        Attendance.objects.create(
            user=self.other_user,branch=self.other_branch,date=timezone.localdate(),
            check_in=now-timedelta(hours=7),check_out=now,status='late',
        )
        response=self.client.get(reverse('employee_attendance',args=[self.employee.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(len(response.context['records']),1)
        self.assertEqual(response.context['stats']['present'],1)
        self.assertEqual(response.context['stats']['worked'],'08:00')

    def test_branch_manager_cannot_open_another_branch_actions(self):
        manager=User.objects.create_user('manager-test',password='pass')
        EmployeeProfile.objects.update_or_create(
            user=manager,
            defaults={'role':'manager','branch':self.branch,'is_active':True},
        )
        self.client.force_login(manager)
        for name in ('employee_reports','employee_attendance','employee_task_create','personnel_action_add','employee_360'):
            response=self.client.get(reverse(name,args=[self.other_employee.pk]))
            self.assertRedirects(response,reverse('employee_list'))
