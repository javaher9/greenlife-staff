from datetime import datetime, timedelta
from urllib.parse import urlsplit
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Attendance, Branch, ReferralLead, ReferralProfile


class LeadCommandRoomTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.manager = User.objects.create_user('command-manager')
        cls.manager.profile.role = 'internal_manager'
        cls.manager.profile.save(update_fields=['role'])
        cls.operator = User.objects.create_user('command-babaei')
        cls.operator.profile.role = 'call_center'
        cls.operator.profile.save(update_fields=['role'])
        cls.source = ReferralProfile.objects.create(
            user=User.objects.create_user('command-source'), referral_code='GLROOM'
        )
        cls.moment = timezone.make_aware(datetime(2026, 11, 21, 11, 30))

    def create_lead(self, number, **fields):
        return ReferralLead.objects.create(
            referrer=self.source, full_name='نام خصوصی نمونه',
            phone=f'0912777{number:04d}', **fields,
        )

    def test_protected_read_only_page(self):
        url = reverse('management_command_room')
        self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.operator)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.manager)
        self.assertEqual(self.client.post(url).status_code, 405)
        response = self.client.get(url)
        self.assertContains(response, 'اتاق فرمان لید')
        self.assertIn('no-store', response['Cache-Control'])
        self.manager.profile.is_active = False
        self.manager.profile.save(update_fields=['is_active'])
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_real_queue_and_operator_counts_follow_saved_changes(self):
        self.client.force_login(self.manager)
        url = reverse('management_command_room')
        with patch('django.utils.timezone.now', return_value=self.moment):
            lead = self.create_lead(1)
            self.create_lead(2, status='contacted')
            self.create_lead(3, status='lost')
            Attendance.objects.bulk_create([Attendance(
                user=self.operator, date=self.moment.date(),
                check_in=self.moment - timedelta(hours=2),
            )])
            first = self.client.get(url)
            self.assertEqual(first.context['unassigned'], 2)
            flower = next(row for row in first.context['flowers'] if row['name'] == 'نرگس')
            self.assertEqual(flower['status'], 'حاضر')
            self.assertEqual(flower['count'], 0)
            self.assertNotContains(first, lead.phone)
            self.assertNotContains(first, lead.full_name)
            self.assertEqual(self.archive_total(first.context['unassigned_url']), 2)

            # Change the fixture's ownership in the test database, then re-read.
            lead.assigned_to = self.operator.profile
            lead.save(update_fields=['assigned_to'])
            Attendance.objects.filter(user=self.operator).update(
                break_started_at=self.moment - timedelta(minutes=2)
            )
            second = self.client.get(url)
            self.assertEqual(second.context['unassigned'], 1)
            self.assertEqual(second.context['total'], 2)
            flower = next(row for row in second.context['flowers'] if row['name'] == 'نرگس')
            self.assertEqual(flower['count'], 1)
            self.assertEqual(flower['status'], 'در وقفه')
            self.assertEqual(self.archive_total(second.context['unassigned_url']), 1)
            self.assertEqual(self.archive_total(flower['url']), 1)

    def test_branch_manager_sees_only_their_branch_flowers(self):
        branch = Branch.objects.create(name='شعبه آزمون اتاق فرمان')
        outside = Branch.objects.create(name='شعبه دیگر اتاق فرمان')
        profile = self.manager.profile
        profile.role = 'manager'
        profile.branch = branch
        profile.save(update_fields=['role', 'branch'])
        self.operator.profile.branch = branch
        self.operator.profile.save(update_fields=['branch'])
        other = User.objects.create_user('command-tavana')
        other.profile.role = 'call_center'
        other.profile.branch = outside
        other.profile.save(update_fields=['role', 'branch'])
        self.client.force_login(self.manager)
        url = reverse('management_command_room')
        response = self.client.get(url)
        self.assertEqual([row['name'] for row in response.context['flowers']], ['نرگس'])
        profile.branch = None
        profile.save(update_fields=['branch'])
        self.assertEqual(self.client.get(url).context['flowers'], [])

    def archive_total(self, url):
        response = self.client.get(
            reverse('management_all_leads_data') + '?' + urlsplit(url).query
        )
        self.assertEqual(response.status_code, 200)
        return response.json()['total']
