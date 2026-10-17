from collections import Counter
from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.lead_routing import (
    assign_external_lead, assign_referral_lead, assign_social_lead,
    eligible_operator_user_ids, operator_routing_summary, release_pending_leads_if_ready,
)
from core.models import (
    Attendance, CallCenterRoutingDay, LeaveRequest, ReferralLead,
    ReferralProfile, StaffNotification,
)


class MorningLeadDistributionTests(TestCase):
    def at(self, hour, minute=0, second=0):
        return timezone.make_aware(datetime(2026, 10, 17, hour, minute, second))

    def setUp(self):
        clock = patch('django.utils.timezone.now', return_value=self.at(8))
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        source_user = User.objects.create_user(username='morning-source')
        self.source = ReferralProfile.objects.create(user=source_user, referral_code='MORNING-TEST')
        self.operators = []
        for name in ('narges', 'tavana', 'yasaman', 'khorshidi', 'abbasi'):
            user = User.objects.create_user(username=f'{name}-morning')
            profile = user.profile
            profile.role = 'call_center'
            profile.is_active = True
            profile.save(update_fields=['role', 'is_active'])
            self.operators.append(profile)
        self.serial = 0

    def leads(self, count, *, overnight=True):
        result = []
        for _ in range(count):
            self.serial += 1
            lead = ReferralLead.objects.create(
                referrer=self.source, full_name=f'تست {self.serial}',
                phone=f'091900{self.serial:05d}', status='new',
                notes='[channel:website]', source='link',
            )
            if overnight:
                ReferralLead.objects.filter(pk=lead.pk).update(created_at=timezone.localtime().replace(hour=0, minute=0, second=0)-timedelta(hours=1))
            result.append(lead)
        return result

    def arrive(self, index):
        Attendance.objects.update_or_create(
            user=self.operators[index].user, date=self.clock.return_value.date(),
            defaults={'check_in':self.clock.return_value, 'check_out':None, 'status':'present'},
        )

    def shares(self):
        counts = Counter(ReferralLead.objects.values_list('assigned_to_id', flat=True))
        return [counts[operator.pk] for operator in self.operators]

    def test_each_arrival_receives_fixed_twenty_percent_only_once(self):
        self.leads(20)
        self.arrive(0)
        self.assertEqual(release_pending_leads_if_ready(), 4)
        self.assertEqual(release_pending_leads_if_ready(force=True), 0)
        self.clock.return_value = self.at(9)
        self.arrive(1)
        self.assertEqual(release_pending_leads_if_ready(), 4)
        self.arrive(0)  # Repeat attendance save must not grant a second share.
        self.assertEqual(release_pending_leads_if_ready(), 0)
        self.assertEqual(self.shares(), [4, 4, 0, 0, 0])
        self.assertEqual(StaffNotification.objects.filter(notification_type='call_center_lead').count(), 8)

    def test_cutoff_balances_all_four_including_not_yet_present_without_moving_owners(self):
        self.leads(20)
        self.arrive(0)
        release_pending_leads_if_ready()
        old_owners = dict(ReferralLead.objects.exclude(assigned_to=None).values_list('pk', 'assigned_to_id'))
        ReferralLead.objects.filter(pk__in=old_owners).update(status='contacted', contact_result='no_answer')
        self.clock.return_value = self.at(10, 14, 59)
        self.assertEqual(release_pending_leads_if_ready(), 0)
        self.clock.return_value = self.at(10, 15)
        self.assertEqual(release_pending_leads_if_ready(), 16)
        self.assertEqual(self.shares(), [5, 5, 5, 5, 0])
        self.assertEqual(dict(ReferralLead.objects.filter(pk__in=old_owners).values_list('pk', 'assigned_to_id')), old_owners)
        self.assertEqual(release_pending_leads_if_ready(), 0)
        self.assertEqual(CallCenterRoutingDay.objects.count(), 1)

    def test_new_morning_leads_do_not_inflate_opening_share(self):
        self.leads(20)
        self.arrive(0)
        release_pending_leads_if_ready()
        self.clock.return_value = self.at(9)
        newcomers = self.leads(5, overnight=False)
        self.arrive(1)
        self.assertEqual(release_pending_leads_if_ready(), 4)
        self.assertEqual(ReferralLead.objects.filter(pk__in=[x.pk for x in newcomers], assigned_to=None).count(), 5)
        self.clock.return_value = self.at(10, 15)
        release_pending_leads_if_ready()
        self.assertEqual(sum(self.shares()), 25)
        self.assertLessEqual(max(self.shares()[:4])-min(self.shares()[:4]), 1)

    def test_empty_opening_queue_remains_a_fixed_zero_snapshot(self):
        self.arrive(0)
        release_pending_leads_if_ready()
        self.leads(10, overnight=False)
        self.arrive(1)
        self.assertEqual(release_pending_leads_if_ready(), 0)
        self.assertEqual(CallCenterRoutingDay.objects.get().opening_lead_ids, [])
        self.clock.return_value = self.at(10, 15)
        self.assertEqual(release_pending_leads_if_ready(), 10)

    def test_settlement_runs_when_no_operator_is_present(self):
        self.leads(20)
        self.assertEqual(release_pending_leads_if_ready(), 0)
        self.clock.return_value = self.at(10, 15)
        self.assertEqual(release_pending_leads_if_ready(), 20)
        self.assertEqual(self.shares(), [5, 5, 5, 5, 0])

    def test_post_cutoff_new_leads_use_present_rotation_and_never_rebalance_old_leads(self):
        self.leads(20)
        self.arrive(0)
        release_pending_leads_if_ready()
        self.clock.return_value = self.at(10, 15)
        release_pending_leads_if_ready()
        old_owners = dict(ReferralLead.objects.values_list('pk', 'assigned_to_id'))
        self.clock.return_value = self.at(11)
        self.arrive(1)
        new_leads = self.leads(4, overnight=False)
        self.assertEqual(release_pending_leads_if_ready(), 4)
        new_counts = Counter(ReferralLead.objects.filter(pk__in=[x.pk for x in new_leads]).values_list('assigned_to_id', flat=True))
        self.assertEqual([new_counts[self.operators[i].pk] for i in (0, 1)], [2, 2])
        self.assertEqual(dict(ReferralLead.objects.filter(pk__in=old_owners).values_list('pk', 'assigned_to_id')), old_owners)

    def test_all_ingestion_channels_respect_the_morning_limit(self):
        self.leads(20)
        self.arrive(0)
        release_pending_leads_if_ready()
        for assign in (lambda lead:assign_external_lead(lead, 'website'), assign_referral_lead, assign_social_lead):
            lead = self.leads(1, overnight=False)[0]
            self.assertIsNone(assign(lead))
        self.assertEqual(self.shares(), [4, 0, 0, 0, 0])

    def test_leave_inactive_blocked_and_future_checkins_are_excluded(self):
        self.leads(20)
        self.arrive(0)
        self.arrive(4)
        self.operators[3].is_active = False
        self.operators[3].save(update_fields=['is_active'])
        LeaveRequest.objects.create(user=self.operators[1].user, start_date=self.at(8).date(),
                                    end_date=self.at(8).date(), status='approved')
        Attendance.objects.create(user=self.operators[2].user, date=self.at(8).date(),
                                  check_in=self.at(11), status='present')
        self.assertEqual(eligible_operator_user_ids(), {self.operators[0].user_id})
        self.assertEqual(release_pending_leads_if_ready(), 4)
        self.clock.return_value = self.at(10, 15)
        release_pending_leads_if_ready()
        self.assertEqual(self.shares(), [10, 0, 10, 0, 0])

    def test_friday_preserves_duty_exception(self):
        self.clock.return_value = self.at(8)-timedelta(days=1)
        self.leads(20)
        self.arrive(0)
        self.assertEqual(release_pending_leads_if_ready(), 20)
        self.assertEqual(self.shares(), [20, 0, 0, 0, 0])

    def test_dashboard_counts_old_leads_assigned_today_and_shows_actual_routing_status(self):
        self.leads(20)
        self.arrive(0)
        release_pending_leads_if_ready()
        self.client.force_login(self.operators[0].user)
        response = self.client.get(reverse('call_center_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['stats']['today'], 4)
        self.assertEqual(response.context['performance']['lead_share_today'], 100)
        self.assertContains(response, 'تسویه نهایی ساعت 10:15')
        self.assertContains(response, 'دریافت‌شده: 4')
        self.assertIn('غیرفعال', operator_routing_summary(self.operators[4]))


class MorningRoutingWorkerTests(TestCase):
    def test_worker_ticks_routing_without_browser_or_sms_calls(self):
        with patch('core.management.commands.process_lead_queue.release_pending_leads_if_ready', return_value=4) as routing, \
             patch('core.sms_automation.process_due_sms') as sms:
            call_command('process_lead_queue', stdout=StringIO())
        routing.assert_called_once_with()
        sms.assert_not_called()

    def test_worker_retries_failed_tick(self):
        with patch('core.management.commands.process_lead_queue.release_pending_leads_if_ready', side_effect=[RuntimeError('test'), 0]) as routing, \
             patch('core.management.commands.process_lead_queue.time.sleep', side_effect=[None, KeyboardInterrupt]), \
             self.assertLogs('core.management.commands.process_lead_queue', level='ERROR'), \
             self.assertRaises(KeyboardInterrupt):
            call_command('process_lead_queue', loop=True, stdout=StringIO())
        self.assertEqual(routing.call_count, 2)
