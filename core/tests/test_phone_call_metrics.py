from datetime import datetime, time, timedelta
import json
from unittest.mock import patch
from uuid import uuid4

from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.phone_call_metric_models import PhoneCallMetric
from core.phone_call_metrics import metric_report


class PhoneCallMetricTests(TestCase):
    token = 'phone-metrics-test-token-not-a-real-secret'

    def setUp(self):
        environment = patch.dict('os.environ', {'STAFF_PHONE_METRICS_TOKEN': self.token})
        environment.start()
        self.addCleanup(environment.stop)
        self.endpoint = reverse('phone_center_ingest_metric')
        self.client = Client(enforce_csrf_checks=True)
        self.tz = timezone.get_default_timezone()
        self.today = timezone.localdate(timezone=self.tz)
        self.yesterday = self.today - timedelta(days=1)
        self.payload = {
            'call_id': str(uuid4()),
            'direction': 'inbound',
            'outcome': 'answered',
            'occurred_at': datetime.combine(self.yesterday, time(23, 59), tzinfo=self.tz).isoformat(),
            'duration_seconds': 90,
        }

    def _post(self, update=None, *, token=None):
        return self.client.post(
            self.endpoint,
            data=json.dumps({**self.payload, **(update or {})}),
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer ' + (self.token if token is None else token),
        )

    def _report(self):
        return metric_report(self.yesterday.isoformat(), self.today.isoformat())

    def test_metrics_require_separately_configured_bearer_credential(self):
        with patch.dict('os.environ', {'STAFF_PHONE_METRICS_TOKEN': ''}):
            self.assertEqual(self._post().status_code, 503)
            self.assertFalse(self._report()['configured'])
        self.assertEqual(self._post(token='unrelated-feeder-token').status_code, 401)
        self.assertEqual(self.client.get(self.endpoint).status_code, 405)
        self.assertEqual(self._report()['count'], 0)
        self.assertIsNone(self._report()['average_duration_seconds'])

    def test_retry_reuses_the_same_phone_event(self):
        response = self._post()
        self.assertEqual(response.status_code, 201)
        self.assertIn('no-store', response['Cache-Control'])
        self.assertEqual(self._post().status_code, 200)
        self.assertEqual(self._post({'duration_seconds': 91}).status_code, 409)
        self.assertEqual(PhoneCallMetric.objects.count(), 1)
        self.assertEqual(PhoneCallMetric.objects.get().duration_seconds, 90)

    def test_rejects_untrusted_fields_and_inconsistent_events(self):
        for update in (
            {'phone': 'withheld'},
            {'outcome': 'failed'},
            {'duration_seconds': True},
            {'outcome': 'unanswered'},
            {'direction': 'extension'},
            {'occurred_at': '2026-01-01T00:00:00'},
            {'occurred_at': (timezone.now() + timedelta(hours=5)).isoformat()},
        ):
            with self.subTest(update=update):
                self.assertEqual(self._post(update).status_code, 400)
        self.assertFalse(PhoneCallMetric.objects.exists())

    def test_metrics_use_persisted_outcomes_and_tehran_dates(self):
        self.assertEqual(self._post().status_code, 201)
        earlier_today = datetime.combine(self.today, time.min, tzinfo=self.tz)
        self.assertEqual(self._post({
            'call_id': str(uuid4()),
            'direction': 'outbound',
            'outcome': 'unanswered',
            'occurred_at': earlier_today.isoformat(),
            'duration_seconds': 0,
        }).status_code, 201)
        with timezone.override('UTC'):
            summary = self._report()
        self.assertTrue(summary['configured'])
        self.assertEqual({
            key: summary[key] for key in ('count', 'inbound', 'outbound', 'answered', 'unanswered')
        }, {'count': 2, 'inbound': 1, 'outbound': 1, 'answered': 1, 'unanswered': 1})
        self.assertEqual(summary['average_duration_seconds'], 90.0)
        self.assertEqual(summary['daily'], [
            {'date': self.yesterday, 'count': 1, 'inbound': 1, 'outbound': 0, 'answered': 1, 'unanswered': 0},
            {'date': self.today, 'count': 1, 'inbound': 0, 'outbound': 1, 'answered': 0, 'unanswered': 1},
        ])
        self.assertEqual(metric_report(self.today.isoformat(), self.today.isoformat())['count'], 1)

    def test_database_rejects_unanswered_event_with_conversation_time(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PhoneCallMetric.objects.create(
                call_id=uuid4(), direction='inbound', outcome='unanswered',
                occurred_at=timezone.now(), duration_seconds=1,
            )
