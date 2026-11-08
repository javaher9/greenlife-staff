from datetime import timedelta
from django.contrib.auth import get_user_model
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.sms_interest_models import SmsInterestInvitation


class SmsInterestTests(TestCase):
    def setUp(self):
        self.owner = get_user_model().objects.create_superuser(username='interest-admin', password='test')
        self.item = SmsInterestInvitation.objects.create(number='09001023340', created_by=self.owner)
        self.url = reverse('sms_interest_short', args=[self.item.short_code])

    def test_public_read_does_not_answer_or_expose_number(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, self.item.number)
        self.assertEqual(len(self.item.short_code), 7)
        self.assertEqual(self.client.get(reverse('sms_interest_public', args=[self.item.token])).status_code, 200)
        self.item.refresh_from_db()
        self.assertIsNone(self.item.answered_at)

    def test_choice_and_callback_appear_in_private_inbox(self):
        self.client.post(self.url, {'choice': 'device'})
        self.client.post(self.url, {'action': 'callback'})
        self.item.refresh_from_db()
        first = self.item.callback_at
        self.assertIsNotNone(first)
        self.client.post(self.url, {'action': 'callback'})
        self.item.refresh_from_db()
        self.assertEqual(first, self.item.callback_at)
        self.client.force_login(self.owner)
        response = self.client.get(reverse('sms_interest_inbox'))
        self.assertContains(response, self.item.number)
        self.assertContains(response, 'درخواست تماس ثبت شده')

    def test_later_cancels_callback(self):
        self.client.post(self.url, {'choice': 'weight'})
        self.client.post(self.url, {'action': 'callback'})
        self.client.post(self.url, {'choice': 'later'})
        self.item.refresh_from_db()
        self.assertIsNone(self.item.callback_at)
        self.assertEqual(self.client.post(self.url, {'action': 'callback'}).status_code, 400)

    def test_invalid_and_expired_choices_do_not_write(self):
        self.assertEqual(self.client.post(self.url, {'choice': 'bad'}).status_code, 400)
        SmsInterestInvitation.objects.filter(pk=self.item.pk).update(created_at=timezone.now()-timedelta(days=31))
        self.client.post(self.url, {'choice': 'weight'})
        self.item.refresh_from_db()
        self.assertEqual(self.item.choice, '')

    def test_permissions_and_csrf(self):
        self.assertEqual(self.client.get(reverse('sms_interest_inbox')).status_code, 302)
        user = get_user_model().objects.create_user(username='ordinary', password='test')
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse('sms_interest_inbox')).status_code, 403)
        self.assertEqual(Client(enforce_csrf_checks=True).post(self.url, {'choice': 'device'}).status_code, 403)

    def test_create_test_invitation(self):
        self.client.force_login(self.owner)
        self.assertEqual(self.client.post(reverse('sms_interest_inbox'), {'number':'invalid'}).status_code, 400)
        response = self.client.post(reverse('sms_interest_inbox'), {'number':'09001023340'}, follow=True)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'باز کردن صفحه چهارگزینه‌ای')
        self.assertContains(response, '/g/')
        self.assertNotContains(response, '/s/c/interest/')
