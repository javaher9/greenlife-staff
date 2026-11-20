"""Isolated regression tests for the executive's one-time Friday queue reset."""
from datetime import datetime, timedelta
from importlib import import_module
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.apps import apps
from django.contrib.auth.models import User
from django.db import connection
from django.test import TestCase, override_settings
from django.utils import timezone

from core.models import (
    AuditLog, Branch, EmployeeProfile, LeadFollowUpLog,
    ReferralLead, ReferralProfile, VisitAppointment,
)

migration = import_module(
    "core.migrations.0136_one_time_200_new_leads_to_saturday_queue"
)


@override_settings(TIME_ZONE="Asia/Tehran")
class OneTime200LeadRequeueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.operator1 = User.objects.create_user("reset-narges", first_name="نرگس")
        cls.operator2 = User.objects.create_user("reset-banafsheh", first_name="بنفشه")
        for u in (cls.operator1, cls.operator2):
            EmployeeProfile.objects.update_or_create(
                user=u, defaults={"role": "call_center", "is_active": True}
            )
        source = User.objects.create_user("reset-source")
        cls.referrer = ReferralProfile.objects.create(
            user=source, referral_code="REQUEUE200NOV20", created_by=source
        )
        cls.group = cls._group()
        base = timezone.now() - timedelta(days=1)
        cls.eligible = ReferralLead.objects.bulk_create([
            ReferralLead(
                referrer=cls.referrer, full_name=f"New lead {i}",
                phone=f"091277{i:05d}",
                status="new", contact_result="",
                assigned_to=(cls.operator1 if i % 2 else cls.operator2).profile,
                assigned_at=base, group=cls.group,
            )
            for i in range(205)
        ])
        cls.excluded_attempt = cls._lead("attempt")
        LeadFollowUpLog.objects.create(
            lead=cls.excluded_attempt, action="attempt", result="",
            actor=cls.operator1,
        )
        cls.excluded_appointment = cls._lead("appointment")
        branch = Branch.objects.create(name="Requeue test branch")
        VisitAppointment.objects.create(
            lead=cls.excluded_appointment, branch=branch,
            full_name="Has booking", phone=cls.excluded_appointment.phone,
            appointment_date=timezone.localdate()+timedelta(days=3),
            appointment_time="11:00", status="booked",
        )
        cls.excluded_contacted = cls._lead("recorded")
        ReferralLead.objects.filter(pk=cls.excluded_contacted.pk).update(
            status="contacted", contact_result="no_answer",
        )

    @classmethod
    def _group(cls):
        from core.models import CallCenterLeadGroup
        return CallCenterLeadGroup.objects.create(name="One-time Nov20 test", is_default=False)

    @classmethod
    def _lead(cls, postfix):
        return ReferralLead.objects.create(
            referrer=cls.referrer, full_name="Excluded " + postfix,
            phone={"attempt":"09128880001","appointment":"09128880002","recorded":"09128880003"}[postfix],
            status="new", contact_result="",
            assigned_to=cls.operator1.profile, group=cls.group,
        )

    @staticmethod
    def _run_at(local_time):
        with override_settings(DEBUG=False):
            with patch.object(migration.timezone, "localtime", return_value=local_time):
                migration.requeue_latest_untouched(
                    apps, SimpleNamespace(connection=connection)
                )

    def test_exactly_newest_200_across_both_operators_and_full_audit(self):
        when=datetime(2026,11,20,19,10,tzinfo=ZoneInfo("Asia/Tehran"))
        self._run_at(when)
        expected_ids={lead.pk for lead in self.eligible[-200:]}
        actual_ids=set(
            ReferralLead.objects.filter(pk__in=[l.pk for l in self.eligible],
                                        assigned_to__isnull=True)
            .values_list("pk", flat=True)
        )
        self.assertSetEqual(actual_ids, expected_ids)
        self.assertEqual(ReferralLead.objects.filter(
            pk__in=expected_ids, status="new", contact_result="",
            assigned_at__isnull=True, group=self.group
        ).count(),200)
        self.assertEqual(ReferralLead.objects.filter(
            pk__in=[l.pk for l in self.eligible[:5]], assigned_to__isnull=False
        ).count(),5)
        for excluded in (self.excluded_attempt,self.excluded_appointment,self.excluded_contacted):
            excluded.refresh_from_db()
            self.assertIsNotNone(excluded.assigned_to_id)
        self.assertEqual(AuditLog.objects.filter(
            path="/ops/one-time-requeue-20261120/",
            object_type="ReferralLead"
        ).count(),200)
        batch=AuditLog.objects.get(object_type="ReferralLeadBatch",
                                  object_id=migration.BATCH_KEY)
        self.assertEqual(batch.metadata["updated"],200)
        self.assertEqual(set(batch.metadata["lead_ids"]),expected_ids)

    def test_no_later_action_and_debug_never_changes_live_ownership(self):
        tomorrow=datetime(2026,11,21,8,1,tzinfo=ZoneInfo("Asia/Tehran"))
        self._run_at(tomorrow)
        self.assertEqual(ReferralLead.objects.filter(
            pk__in=[l.pk for l in self.eligible],assigned_to__isnull=True
        ).count(),0)
        with override_settings(DEBUG=True):
            migration.requeue_latest_untouched(
                apps, SimpleNamespace(connection=connection)
            )
        self.assertEqual(AuditLog.objects.filter(
            object_id=migration.BATCH_KEY
        ).count(),0)
