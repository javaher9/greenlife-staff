from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Branch, EmployeeProfile, InternalConversation, InternalMessage, StaffNotification


class InternalMessagingTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='پیام تست')
        self.sender=self.make_user('msg-sender','call_center','فرستنده')
        self.receiver=self.make_user('msg-receiver','receptionist','گیرنده')
        self.third=self.make_user('msg-third','employee','شخص سوم')
        self.external=self.make_user('msg-referrer','referrer','معرف')

    def make_user(self,username,role,first_name):
        user=User.objects.create_user(username=username,password='pass123456',first_name=first_name)
        EmployeeProfile.objects.update_or_create(
            user=user,
            defaults={'role':role,'branch':self.branch,'job_title':role,'is_active':True},
        )
        return User.objects.get(pk=user.pk)

    def test_staff_can_create_private_or_group_conversation(self):
        self.client.force_login(self.sender)
        response=self.client.post(reverse('internal_message_new'),{
            'title':'هماهنگی تست',
            'participants':[self.receiver.pk,self.third.pk],
            'first_message':'سلام، این یک پیام داخلی است.',
        })
        conversation=InternalConversation.objects.get(title='هماهنگی تست')
        self.assertRedirects(response,reverse('internal_message_thread',args=[conversation.pk]))
        self.assertEqual(set(conversation.participants.values_list('pk',flat=True)),{
            self.sender.pk,self.receiver.pk,self.third.pk,
        })
        message=conversation.messages.get()
        self.assertEqual(message.sender,self.sender)
        self.assertIn('پیام داخلی',message.body)
        self.assertTrue(message.read_by.filter(pk=self.sender.pk).exists())
        self.assertTrue(StaffNotification.objects.filter(
            user=self.receiver,notification_type='internal_message',
        ).exists())

    def test_non_participant_cannot_read_thread(self):
        conversation=InternalConversation.objects.create(created_by=self.sender)
        conversation.participants.add(self.sender,self.receiver)
        InternalMessage.objects.create(conversation=conversation,sender=self.sender,body='خصوصی')
        self.client.force_login(self.third)
        self.assertEqual(
            self.client.get(reverse('internal_message_thread',args=[conversation.pk])).status_code,
            404,
        )

    def test_recipient_can_reply_and_poll_updates(self):
        conversation=InternalConversation.objects.create(created_by=self.sender)
        conversation.participants.add(self.sender,self.receiver)
        first=InternalMessage.objects.create(conversation=conversation,sender=self.sender,body='پیام اول')
        self.client.force_login(self.receiver)
        response=self.client.post(reverse('internal_message_thread',args=[conversation.pk]),{'body':'پاسخ من'})
        self.assertRedirects(response,reverse('internal_message_thread',args=[conversation.pk]))
        reply=conversation.messages.order_by('-pk').first()
        self.assertEqual(reply.sender,self.receiver)
        self.assertEqual(reply.body,'پاسخ من')
        response=self.client.get(reverse('internal_message_updates',args=[conversation.pk]),{'after':first.pk})
        self.assertEqual(response.status_code,200)
        payload=response.json()
        self.assertTrue(payload['ok'])
        self.assertEqual(payload['messages'][0]['body'],'پاسخ من')

    def test_opening_thread_marks_incoming_messages_read(self):
        conversation=InternalConversation.objects.create(created_by=self.sender)
        conversation.participants.add(self.sender,self.receiver)
        item=InternalMessage.objects.create(conversation=conversation,sender=self.sender,body='خوانده نشده')
        self.client.force_login(self.receiver)
        response=self.client.get(reverse('internal_message_thread',args=[conversation.pk]))
        self.assertEqual(response.status_code,200)
        self.assertTrue(item.read_by.filter(pk=self.receiver.pk).exists())

    def test_referrer_cannot_use_staff_cartable(self):
        self.client.force_login(self.external)
        self.assertEqual(self.client.get(reverse('internal_message_inbox')).status_code,403)
        self.assertEqual(self.client.get(reverse('internal_message_new')).status_code,403)

    def test_call_center_dashboard_uses_new_clean_workspace_and_message_link(self):
        self.client.force_login(self.sender)
        response=self.client.get(reverse('call_center_dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'class="cc2"')
        self.assertContains(response,'پیام داخلی')
        self.assertContains(response,'نوبت‌های امروز من')
        self.assertContains(response,'background:#fff!important')
        self.assertNotContains(response,'میز کار کال‌سنتر')

    def test_receptionist_dashboard_cartable_points_to_real_messages(self):
        self.client.force_login(self.receiver)
        response=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        )
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'href="/messages/"')
        self.assertContains(response,'کارتابل داخلی')
        self.assertContains(response,'href="/service-requests/"')
