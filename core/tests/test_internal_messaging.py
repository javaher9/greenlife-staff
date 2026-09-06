from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Branch, EmployeeProfile, InternalMessage, StaffNotification


class InternalMessagingTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='پیام تست')
        self.call_center=self.make_user('msg-call','call_center','نرگس')
        self.receptionist=self.make_user('msg-reception','receptionist','منشی')
        self.employee=self.make_user('msg-employee','employee','کارمند')
        self.referrer=self.make_user('msg-referrer','referrer','معرف')

    def make_user(self,username,role,first_name):
        user=User.objects.create_user(
            username=username,password='pass123456',first_name=first_name
        )
        EmployeeProfile.objects.update_or_create(
            user=user,
            defaults={'role':role,'branch':self.branch,'is_active':True},
        )
        return User.objects.get(pk=user.pk)

    def test_public_staff_room_is_visible_to_all_staff(self):
        self.client.force_login(self.call_center)
        response=self.client.post(reverse('internal_messages'),{
            'recipient':'all','body':'سلام به همه همکاران',
        })
        self.assertRedirects(response,reverse('internal_messages'))
        item=InternalMessage.objects.get(body='سلام به همه همکاران')
        self.assertIsNone(item.recipient_id)

        self.client.force_login(self.employee)
        response=self.client.get(reverse('internal_messages'))
        self.assertContains(response,'سلام به همه همکاران')

    def test_direct_message_is_private_and_creates_notification(self):
        self.client.force_login(self.call_center)
        response=self.client.post(reverse('internal_messages'),{
            'recipient':str(self.receptionist.pk),'body':'لطفاً نوبت بیمار را چک کنید',
        })
        self.assertEqual(response.status_code,302)
        item=InternalMessage.objects.get(body='لطفاً نوبت بیمار را چک کنید')
        self.assertEqual(item.sender,self.call_center)
        self.assertEqual(item.recipient,self.receptionist)
        self.assertTrue(StaffNotification.objects.filter(
            user=self.receptionist,notification_type='internal_message'
        ).exists())

        self.client.force_login(self.employee)
        response=self.client.get(
            reverse('internal_messages')+'?with='+str(self.call_center.pk)
        )
        self.assertNotContains(response,'لطفاً نوبت بیمار را چک کنید')

    def test_opening_direct_thread_marks_incoming_messages_read(self):
        InternalMessage.objects.create(
            sender=self.call_center,recipient=self.receptionist,body='پیام خوانده نشده'
        )
        self.client.force_login(self.receptionist)
        response=self.client.get(
            reverse('internal_messages')+'?with='+str(self.call_center.pk)
        )
        self.assertEqual(response.status_code,200)
        item=InternalMessage.objects.get(body='پیام خوانده نشده')
        self.assertIsNotNone(item.read_at)

    def test_every_active_staff_member_is_available_as_direct_recipient(self):
        self.client.force_login(self.call_center)
        response=self.client.get(reverse('internal_messages'))
        self.assertContains(response,self.receptionist.get_full_name())
        self.assertContains(response,self.employee.get_full_name())
        self.assertNotContains(response,self.referrer.get_full_name())

    def test_referrer_cannot_access_staff_messages(self):
        self.client.force_login(self.referrer)
        self.assertEqual(self.client.get(reverse('internal_messages')).status_code,403)

    def test_call_center_dashboard_links_real_messaging_and_uses_white_shell_class(self):
        self.client.force_login(self.call_center)
        response=self.client.get(reverse('call_center_dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'شعار امروز')
        self.assertContains(response,'هر تماس، یک قدم برای حال بهتر')
        self.assertContains(response,'پیام داخلی')
        self.assertContains(response,'برنامه نوبت‌های امروز')
        self.assertContains(response,'gl-role-call-center')
