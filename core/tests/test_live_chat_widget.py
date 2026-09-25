from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import Branch, InternalMessage, StaffNotification


class LiveChatWidgetTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='چت تست')
        self.user=User.objects.create_user(
            username='chat-user',
            first_name='کاربر',
            last_name='اول',
            password='StrongPass123',
        )
        self.user.profile.role='doctor'
        self.user.profile.branch=self.branch
        self.user.profile.save(update_fields=['role','branch'])

        self.peer=User.objects.create_user(
            username='chat-peer',
            first_name='کاربر',
            last_name='دوم',
            password='StrongPass123',
        )
        self.peer.profile.role='consultant'
        self.peer.profile.branch=self.branch
        self.peer.profile.save(update_fields=['role','branch'])
        self.client.login(username='chat-user',password='StrongPass123')

    def test_live_widget_state_reports_unread_message(self):
        item=InternalMessage.objects.create(
            sender=self.peer,
            recipient=self.user,
            body='برای این بیمار یک نکته مهم دارم.',
        )
        response=self.client.get(reverse('internal_message_live_widget'))
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertTrue(data['ok'])
        self.assertEqual(data['unread_total'],1)
        self.assertEqual(data['latest_incoming_id'],item.pk)
        self.assertEqual(data['incoming_preview']['sender_id'],self.peer.pk)

    def test_live_widget_thread_marks_selected_sender_read(self):
        InternalMessage.objects.create(
            sender=self.peer,
            recipient=self.user,
            body='پیام تست',
        )
        response=self.client.get(
            reverse('internal_message_live_widget'),
            {'with':self.peer.pk},
        )
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertEqual(data['selected'],self.peer.pk)
        self.assertEqual(data['unread_total'],0)
        self.assertEqual(len(data['thread']),1)
        self.assertIsNotNone(
            InternalMessage.objects.get(sender=self.peer,recipient=self.user).read_at
        )

    def test_live_widget_can_send_without_leaving_current_page(self):
        response=self.client.post(
            reverse('internal_message_live_widget'),
            {'recipient':self.peer.pk,'body':'پاسخ فوری از پنل'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )
        self.assertEqual(response.status_code,200)
        data=response.json()
        self.assertTrue(data['ok'])
        self.assertTrue(
            InternalMessage.objects.filter(
                sender=self.user,
                recipient=self.peer,
                body='پاسخ فوری از پنل',
            ).exists()
        )
        self.assertTrue(
            StaffNotification.objects.filter(
                user=self.peer,
                notification_type='internal_message',
            ).exists()
        )
