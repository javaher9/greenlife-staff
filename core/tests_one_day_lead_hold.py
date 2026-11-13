"""Regression tests for the non-recurring Nov 13 Friday lead hold."""
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, override_settings

from .lead_routing import (
    ONE_TIME_LEAD_HOLD_DATE,
    _live_assignment_allowed,
    _one_time_lead_hold,
)


@override_settings(TIME_ZONE='Asia/Tehran', USE_TZ=True)
class OneDayLeadHoldTests(SimpleTestCase):
    def local(self, day, hour):
        return datetime(2026, 11, day, hour, 0, tzinfo=ZoneInfo('Asia/Tehran'))

    def test_friday_all_live_assignment_paused(self):
        now = self.local(13, 15)
        self.assertEqual(ONE_TIME_LEAD_HOLD_DATE.isoformat(), '2026-11-13')
        self.assertTrue(_one_time_lead_hold(now))
        self.assertFalse(_live_assignment_allowed(now))

    def test_november_14_resumes_normal_routing(self):
        # Overnight is already held under the ordinary daily policy.
        self.assertFalse(_one_time_lead_hold(self.local(14, 8)))
        self.assertFalse(_live_assignment_allowed(self.local(14, 8)))
        # At 10:15 the usual Saturday live rotation is fully restored.
        self.assertTrue(_live_assignment_allowed(self.local(14, 11)))

    def test_future_fridays_are_not_paused(self):
        future_friday = self.local(20, 15)
        self.assertFalse(_one_time_lead_hold(future_friday))
        self.assertTrue(_live_assignment_allowed(future_friday))
