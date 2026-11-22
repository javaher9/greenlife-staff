from datetime import datetime, time, timedelta
import json
from unittest.mock import patch
from uuid import uuid4

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import EmployeeProfile
from core.phone_rating_models import PhoneCallRating
from core.phone_ratings import rating_report


class PhoneRatingsTests(TestCase):
    token = 'phone-ratings-test-token-not-a-real-secret'

    @classmethod
    def setUpTestData(cls):
        cls.operator = cls._profile('ratings-babaei', 'call_center')
        cls.other_operator = cls._profile('ratings-tavana', 'call_center')
        cls.non_operator = cls._profile('ratings-sales', 'employee')

    @staticmethod
    def _profile(username, role):
        user = get_user_model().objects.create_user(username=username)
        profile, _ = EmployeeProfile.objects.update_or_create(
            user=user, defaults={'role': role, 'is_active': True},
        )
        return profile

    def setUp(self):
        token = patch.dict('os.environ', {'STAFF_PHONE_RATINGS_TOKEN': self.token})
        token.start()
        self.addCleanup(token.stop)
        self.client = Client(enforce_csrf_checks=True)
        self.endpoint = reverse('phone_center_ingest_rating')
        self.payload = {'call_id': str(uuid4()), 'operator_id': self.operator.pk, 'score': 5}

    def _post(self, payload=None, *, token=None):
        return self.client.post(
            self.endpoint,
            data=json.dumps(self.payload if payload is None else payload),
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer ' + (self.token if token is None else token),
        )

    def test_config_required_and_token_is_independent_of_login(self):
        self.assertEqual(self._post(token='wrong').status_code, 401)
        self.client.force_login(self.operator.user)
        request = self.client.post(self.endpoint + '?token=' + self.token, self.payload)
        self.assertEqual(request.status_code, 401)
        with patch.dict('os.environ', {'STAFF_PHONE_RATINGS_TOKEN': ''}):
            self.assertEqual(self._post().status_code, 503)
            self.assertFalse(rating_report({})['configured'])
        self.assertFalse(PhoneCallRating.objects.exists())

    def test_ingestion_is_private_and_retry_safe(self):
        self.assertEqual(self.client.get(self.endpoint).status_code, 405)
        created = self._post()
        self.assertEqual(created.status_code, 201)
        self.assertIn('no-store', created['Cache-Control'])
        self.assertEqual(self._post().status_code, 200)
        self.assertEqual(self._post({**self.payload, 'score': 1}).status_code, 409)
        self.assertEqual(
            self._post({**self.payload, 'operator_id': self.other_operator.pk}).status_code, 409,
        )
        self.assertEqual(PhoneCallRating.objects.count(), 1)
        self.assertEqual(PhoneCallRating.objects.get().score, 5)
        self.assertEqual(rating_report({})['count'], 1)

    def test_only_pbx_call_uuid_active_operator_and_integer_score_are_accepted(self):
        for update in (
            {'phone': 'withheld'},
            {'call_id': 'raw-pbx-linked-id'},
            {'score': True},
            {'score': '3'},
            {'score': 6},
            {'operator_id': self.non_operator.pk},
        ):
            with self.subTest(update=update):
                self.assertEqual(self._post({**self.payload, **update}).status_code, 400)
        EmployeeProfile.objects.filter(pk=self.operator.pk).update(is_active=False)
        self.assertEqual(self._post().status_code, 400)
        self.assertFalse(PhoneCallRating.objects.exists())

    def test_database_enforces_rating_range(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            PhoneCallRating.objects.create(call_id=uuid4(), operator=self.operator, score=0)

    def test_report_uses_tehran_days_and_real_breakdowns(self):
        tz = timezone.get_default_timezone()
        today = timezone.localdate(timezone=tz)
        yesterday = today - timedelta(days=1)
        first = PhoneCallRating.objects.create(call_id=uuid4(), operator=self.operator, score=5)
        PhoneCallRating.objects.filter(pk=first.pk).update(
            rated_at=datetime.combine(yesterday, time(23, 59), tzinfo=tz),
        )
        second = PhoneCallRating.objects.create(call_id=uuid4(), operator=self.operator, score=3)
        third = PhoneCallRating.objects.create(call_id=uuid4(), operator=self.other_operator, score=4)
        PhoneCallRating.objects.filter(pk__in=[second.pk, third.pk]).update(
            rated_at=datetime.combine(today, time(0, 1), tzinfo=tz),
        )
        with timezone.override('UTC'):
            report = rating_report({'start': yesterday.isoformat(), 'end': today.isoformat()})
        self.assertTrue(report['configured'])
        self.assertEqual(report['count'], 3)
        self.assertEqual(report['average'], 4)
        self.assertEqual([row['count'] for row in report['distribution']], [0, 0, 1, 1, 1])
        self.assertEqual([row['percentage'] for row in report['distribution']], [0, 0, 33.3, 33.3, 33.3])
        self.assertEqual(
            report['daily'],
            [{'date': yesterday, 'count': 1, 'average': 5}, {'date': today, 'count': 2, 'average': 3.5}],
        )
        self.assertEqual([row['name'] for row in report['by_operator']], ['نرگس', 'بنفشه'])
        filtered = rating_report({'start': today.isoformat(), 'operator': str(self.operator.pk)})
        self.assertEqual(filtered['count'], 1)
        self.assertEqual(filtered['operator'], str(self.operator.pk))
        self.assertEqual(filtered['average'], 3)

    def test_empty_report_undefined_average_and_range_validation(self):
        report = rating_report({'start': '2025-99-99'})
        self.assertTrue(report['error'])
        self.assertEqual(len(report['daily']), 7)
        self.assertEqual(report['count'], 0)
        self.assertIsNone(report['average'])
        self.assertEqual(report['by_operator'], [])
        self.assertTrue(all(not row['count'] and row['average'] is None for row in report['daily']))
