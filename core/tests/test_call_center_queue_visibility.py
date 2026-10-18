from datetime import datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.models import (
    Branch, CallCenterLeadGroup, EmployeeProfile, ReferralLead, ReferralProfile,
)


class CallCenterQueueVisibilityTests(TestCase):
    """A large old backlog must never hide newly assigned leads."""

    @classmethod
    def setUpTestData(cls):
        cls.now = datetime(2026, 10, 18, 12, tzinfo=ZoneInfo('Asia/Tehran'))
        cls.branch = Branch.objects.create(name='Queue visibility')
        cls.operator = User.objects.create_user('queue-khorshidi', first_name='خورشیدی')
        cls.other = User.objects.create_user('queue-other', first_name='نرگس')
        for user in (cls.operator, cls.other):
            EmployeeProfile.objects.update_or_create(
                user=user,
                defaults={'role': 'call_center', 'branch': cls.branch, 'is_active': True},
            )
        source = User.objects.create_user('queue-source')
        cls.referrer = ReferralProfile.objects.create(
            user=source, referral_code='GLQUEUEVIS', created_by=source,
        )
        cls.old_group = CallCenterLeadGroup.objects.create(name='صف قدیمی')
        cls.new_group = CallCenterLeadGroup.objects.create(name='ورودی امروز')
        cls.backlog = ReferralLead.objects.bulk_create([
            ReferralLead(
                referrer=cls.referrer, full_name=f'سابقه {index}',
                phone=f'091210{index:05d}', assigned_to=cls.operator.profile,
                assigned_at=cls.now-timedelta(days=2), group=cls.old_group,
                status='contacted', contact_result='no_answer',
            )
            for index in range(300)
        ])
        cls.fresh = ReferralLead.objects.create(
            referrer=cls.referrer, full_name='لید تازه پس از صف بزرگ',
            phone='09129990001', assigned_to=cls.operator.profile,
            assigned_at=cls.now-timedelta(minutes=5), group=cls.new_group,
        )
        # Created overnight, assigned today: must match the assignment-day KPI.
        ReferralLead.objects.filter(pk=cls.fresh.pk).update(
            created_at=cls.now-timedelta(days=1),
        )
        cls.foreign = ReferralLead.objects.create(
            referrer=cls.referrer, full_name='لید اپراتور دیگر',
            phone='09129990002', assigned_to=cls.other.profile,
            assigned_at=cls.now, group=cls.new_group,
        )

    def setUp(self):
        self.clock = patch('django.utils.timezone.now', return_value=self.now)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.client.force_login(self.operator)

    def dashboard(self, **params):
        response = self.client.get(reverse('call_center_dashboard'), params)
        self.assertEqual(response.status_code, 200)
        return response

    def test_today_count_has_actual_row_after_more_than_250_old_leads(self):
        response = self.dashboard()
        self.assertEqual(response.context['stats']['today'], 1)
        rows = response.context['work_queue']
        self.assertIn(self.fresh.pk, [row['lead'].pk for row in rows])
        self.assertEqual(len(rows), 301)
        self.assertEqual(response.context['queue_category_counts']['all'], 301)
        self.assertContains(response, f'data-lead-id="{self.fresh.pk}"')
        self.assertContains(response, f'data-lead-id="{self.backlog[0].pk}"')
        self.assertNotContains(response, f'data-lead-id="{self.foreign.pk}"')

    def test_today_filter_uses_assignment_day_and_legacy_creation_fallback(self):
        legacy = ReferralLead.objects.create(
            referrer=self.referrer, full_name='دریافتی قدیمی بدون زمان تخصیص',
            phone='09129990003', assigned_to=self.operator.profile,
            group=self.new_group,
        )
        ReferralLead.objects.filter(pk=legacy.pk).update(assigned_at=None)
        response = self.dashboard()
        received = [row['lead'].pk for row in response.context['work_queue']
                    if 'receivedtoday' in row['categories'].split()]
        self.assertCountEqual(received, [self.fresh.pk, legacy.pk])
        self.assertEqual(response.context['queue_category_counts']['receivedtoday'], 2)
        self.assertEqual(response.context['stats']['today'], 2)
        self.assertContains(response, 'data-filter="receivedtoday"')

    def test_group_filter_and_ownership_are_preserved(self):
        response = self.dashboard(group=self.new_group.pk)
        self.assertEqual([row['lead'].pk for row in response.context['work_queue']],
                         [self.fresh.pk])
        self.assertEqual(response.context['queue_category_counts']['all'], 1)
        self.assertNotContains(response, f'data-lead-id="{self.foreign.pk}"')

    def test_overdue_priority_and_closed_lead_exclusion_are_preserved(self):
        overdue = self.backlog[-1]
        ReferralLead.objects.filter(pk=overdue.pk).update(
            next_follow_up=self.now.date()-timedelta(days=1),
        )
        closed = self.backlog[0]
        ReferralLead.objects.filter(pk=closed.pk).update(status='lost')
        response = self.dashboard()
        rows = response.context['work_queue']
        self.assertEqual(rows[0]['lead'].pk, overdue.pk)
        self.assertIn(self.fresh.pk, [row['lead'].pk for row in rows])
        self.assertNotIn(closed.pk, [row['lead'].pk for row in rows])
        self.assertEqual(len(rows), 300)
