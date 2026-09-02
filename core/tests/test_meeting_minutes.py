from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.utils import timezone

from core.jalali import format_jalali
from core.models import (
    Branch, EmployeeProfile, MeetingActionItem, MeetingActionStep,
    MeetingActionUpdate, MeetingMinute, StaffNotification, Task,
)


@override_settings(ROOT_URLCONF='greenlife.urls')
class MeetingMinutesTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='نیاوران')
        self.admin=self.make_user('admin','admin','علی','جواهریان')
        self.internal=self.make_user('hashemi','internal_manager','فاطیما','هاشمی')
        self.employee=self.make_user('employee','employee','کارمند','نمونه')
        self.other=self.make_user('other','employee','پرسنل','دیگر')

    def make_user(self,username,role,first_name,last_name):
        user=User.objects.create_user(
            username=username,password='test-password',first_name=first_name,last_name=last_name,
        )
        EmployeeProfile.objects.update_or_create(
            user=user,defaults={'role':role,'branch':self.branch,'is_active':True},
        )
        return User.objects.get(pk=user.pk)

    def create_payload(self):
        return {
            'title':'جلسه پیگیری عملیات','meeting_date':format_jalali(timezone.localdate()),
            'start_time':'10:30','location':'دفتر نیاوران','attendees':[self.internal.pk,self.employee.pk],
            'summary':'جمع‌بندی جلسه آزمایشی',
            'actions-TOTAL_FORMS':'1','actions-INITIAL_FORMS':'0','actions-MIN_NUM_FORMS':'0','actions-MAX_NUM_FORMS':'12',
            'actions-0-title':'پیگیری خرید اقلام مصرفی','actions-0-assigned_to':str(self.employee.pk),
            'actions-0-due_date':format_jalali(timezone.localdate()+timedelta(days=2)),
            'actions-0-priority':'high','actions-0-description':'خرید و ارائه فاکتور',
        }

    def create_meeting(self):
        self.client.force_login(self.internal)
        response=self.client.post('/meeting-minutes/new/',self.create_payload())
        self.assertEqual(response.status_code,302)
        return MeetingMinute.objects.get()

    def test_internal_manager_navigation_and_pages_are_available(self):
        self.client.force_login(self.internal)
        response=self.client.get('/meeting-minutes/new/')
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'صورت‌جلسه جدید')
        self.assertContains(response,'لیست صورت‌جلسات')
        response=self.client.get('/meeting-minutes/')
        self.assertEqual(response.status_code,200)

    def test_regular_manager_and_employee_cannot_open_meeting_archive(self):
        manager=self.make_user('manager','manager','مدیر','شعبه')
        for user in (manager,self.employee):
            self.client.force_login(user)
            response=self.client.get('/meeting-minutes/')
            self.assertRedirects(response,'/',fetch_redirect_response=False)

    def test_creation_delegates_action_to_staff_task_and_notification(self):
        meeting=self.create_meeting()
        self.assertEqual(meeting.created_by,self.internal)
        self.assertEqual(meeting.attendees.count(),2)
        action=meeting.action_items.get()
        self.assertEqual(action.assigned_to,self.employee)
        self.assertIsNotNone(action.task_id)
        self.assertEqual(action.task.assigned_to,self.employee)
        self.assertTrue(action.task.title.startswith('[مصوبه]'))
        self.assertTrue(StaffNotification.objects.filter(user=self.employee,notification_type='meeting_action').exists())

    def test_delegated_action_appears_in_my_tasks_and_uses_action_page(self):
        meeting=self.create_meeting(); action=meeting.action_items.get()
        self.client.force_login(self.employee)
        response=self.client.get('/tasks/')
        self.assertContains(response,'پیگیری خرید اقلام مصرفی')
        self.assertContains(response,f'/meeting-actions/{action.pk}/')

    def test_employee_submits_completion_for_internal_manager_approval(self):
        meeting=self.create_meeting(); action=meeting.action_items.get()
        self.client.force_login(self.employee)
        response=self.client.post(f'/meeting-actions/{action.pk}/',{
            'action':'progress','progress-status':'awaiting_approval','progress-note':'کار انجام و فاکتور ارسال شد.',
        })
        self.assertRedirects(response,f'/meeting-actions/{action.pk}/',fetch_redirect_response=False)
        action.refresh_from_db(); action.task.refresh_from_db()
        self.assertEqual(action.status,'awaiting_approval')
        self.assertEqual(action.task.status,'doing')
        self.assertTrue(MeetingActionUpdate.objects.filter(action=action,user=self.employee).exists())

    def test_internal_manager_approval_completes_linked_task(self):
        meeting=self.create_meeting(); action=meeting.action_items.get()
        action.status='awaiting_approval'; action.save()
        self.client.force_login(self.internal)
        response=self.client.post(f'/meeting-actions/{action.pk}/',{
            'action':'progress','progress-status':'done','progress-note':'مدرک بررسی و تأیید شد.',
        })
        self.assertEqual(response.status_code,302)
        action.refresh_from_db(); action.task.refresh_from_db()
        self.assertEqual(action.status,'done')
        self.assertEqual(action.task.status,'done')
        self.assertEqual(action.approved_by,self.internal)

    def test_other_employee_cannot_update_someone_elses_action(self):
        meeting=self.create_meeting(); action=meeting.action_items.get()
        self.client.force_login(self.other)
        response=self.client.get(f'/meeting-actions/{action.pk}/')
        self.assertRedirects(response,'/tasks/',fetch_redirect_response=False)

    def test_steps_calculate_progress_and_can_be_checked(self):
        meeting=self.create_meeting(); action=meeting.action_items.get()
        first=MeetingActionStep.objects.create(action=action,title='مرحله اول',sort_order=0)
        MeetingActionStep.objects.create(action=action,title='مرحله دوم',sort_order=1)
        self.assertEqual(action.progress_percent,0)
        self.client.force_login(self.employee)
        response=self.client.post(f'/meeting-steps/{first.pk}/toggle/')
        self.assertEqual(response.status_code,302)
        first.refresh_from_db()
        self.assertTrue(first.is_done)
        action=MeetingActionItem.objects.prefetch_related('steps').get(pk=action.pk)
        self.assertEqual(action.progress_percent,50)

    def test_admin_graphical_dashboard_has_colored_kpis_and_assignment(self):
        meeting=self.create_meeting(); action=meeting.action_items.get()
        self.client.force_login(self.admin)
        response=self.client.get('/meeting-minutes/dashboard/')
        self.assertEqual(response.status_code,200)
        for css_class in ('kpi-purple','kpi-blue','kpi-gold','kpi-red'):
            self.assertContains(response,css_class)
        self.assertContains(response,action.title)
        self.assertContains(response,self.employee.get_full_name())
