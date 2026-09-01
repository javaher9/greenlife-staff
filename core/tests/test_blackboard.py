from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import BlackboardMessage, Branch, EmployeeProfile


class StaffBlackboardTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='نیاوران')
        self.other_branch=Branch.objects.create(name='پونک')
        self.staff=User.objects.create_user('board-staff',password='pass',first_name='مریم')
        EmployeeProfile.objects.update_or_create(user=self.staff,defaults={'role':'employee','branch':self.branch,'is_active':True})
        self.admin=User.objects.create_user('board-admin',password='pass')
        EmployeeProfile.objects.update_or_create(user=self.admin,defaults={'role':'admin','branch':self.branch,'is_active':True})
        self.client.force_login(self.staff)

    def test_default_blackboard_is_visible_without_database_message(self):
        response=self.client.get(reverse('dashboard'))
        self.assertContains(response,'gl-blackboard')
        self.assertContains(response,'امروز می‌ترکونیم! شبکه فروشت یادت نره.')

    def test_branch_message_overrides_global_and_other_branch(self):
        BlackboardMessage.objects.create(title='پیام عمومی',message='برای همه شعب',created_by=self.admin)
        BlackboardMessage.objects.create(title='پیام پونک',message='فقط پونک',branch=self.other_branch,created_by=self.admin)
        BlackboardMessage.objects.create(title='پیام نیاوران',message='هدف امروز نیاوران',branch=self.branch,created_by=self.admin)
        response=self.client.get(reverse('dashboard'))
        self.assertContains(response,'پیام نیاوران')
        self.assertContains(response,'هدف امروز نیاوران')
        self.assertNotContains(response,'فقط پونک')
        self.assertNotContains(response,'برای همه شعب')

    def test_employee_cannot_manage_blackboard(self):
        response=self.client.get(reverse('blackboard_manage'))
        self.assertRedirects(response,reverse('dashboard'))

    def test_admin_can_publish_blackboard_message(self):
        self.client.force_login(self.admin)
        response=self.client.post(reverse('blackboard_create'),{
            'title':'یادآوری امروز','message':'شبکه فروشت یادت نره','branch':self.branch.pk,'is_active':'on',
        })
        self.assertRedirects(response,reverse('blackboard_manage'))
        board=BlackboardMessage.objects.get()
        self.assertEqual(board.branch,self.branch)
        self.assertEqual(board.created_by,self.admin)
        self.assertTrue(board.is_active)
