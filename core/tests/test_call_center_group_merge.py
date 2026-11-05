import importlib

from django.apps import apps
from django.test import TestCase
from django.urls import reverse

from core.models import AuditLog, CallCenterLeadGroup, ReferralLead
from core.tests.test_call_center_role import CallCenterRoleTests


merge = importlib.import_module('core.migrations.0109_merge_duplicate_call_center_groups').merge_duplicate_groups
merge_doctor = importlib.import_module('core.migrations.0110_merge_doctor_desk_and_vip_groups').merge_groups


class CallCenterGroupMergeTests(TestCase):
    setUp = CallCenterRoleTests.setUp
    make_user = CallCenterRoleTests.make_user

    def test_aliases_keep_leads_and_canonical_group(self):
        target = CallCenterLeadGroup.objects.get(name='میزهای قدیمی دکتر جواهریان')
        source = CallCenterLeadGroup.objects.create(name='میزهای آقای دکتر', is_default=True)
        distinct = CallCenterLeadGroup.objects.create(name='میزهای جدید آقای دکتر')
        self.lead_one.group = source
        self.lead_one.save(update_fields=['group'])
        self.lead_two.group = distinct
        self.lead_two.save(update_fields=['group'])
        before = ReferralLead.objects.count()

        merge(apps, None)

        self.lead_one.refresh_from_db()
        self.lead_two.refresh_from_db()
        target.refresh_from_db()
        self.assertEqual(ReferralLead.objects.count(), before)
        self.assertEqual(self.lead_one.group_id, target.pk)
        self.assertEqual(self.lead_two.group_id, distinct.pk)
        self.assertTrue(target.is_default)
        self.assertFalse(CallCenterLeadGroup.objects.filter(pk=source.pk).exists())
        self.assertEqual(AuditLog.objects.get(action='call_center_group_merge').metadata['leads_moved'], 1)

    def test_normalized_persian_and_spacing_are_idempotent(self):
        target = CallCenterLeadGroup.objects.create(name='پیگیری  ویژه')
        source = CallCenterLeadGroup.objects.create(name='پيگيري ویژه')
        self.lead_one.group = source
        self.lead_one.save(update_fields=['group'])
        self.lead_two.group = target
        self.lead_two.save(update_fields=['group'])
        merge(apps, None)
        self.lead_one.refresh_from_db()
        self.assertEqual(self.lead_one.group_id, target.pk)
        self.assertFalse(CallCenterLeadGroup.objects.filter(pk=source.pk).exists())
        count = AuditLog.objects.filter(action='call_center_group_merge').count()
        merge(apps, None)
        self.assertEqual(AuditLog.objects.filter(action='call_center_group_merge').count(), count)

    def test_doctor_desk_typos_and_vip_case_merge_without_losing_leads(self):
        doctor = CallCenterLeadGroup.objects.get(name='میزهای قدیمی دکتر جواهریان')
        vip = CallCenterLeadGroup.objects.get(name='VIP')
        names = ['مزوهای قدیمی آقای دکتر', 'مزو های قدیمی آقای دکتر', 'مزوهای قدیمی دکتر جواهریان']
        sources = [CallCenterLeadGroup.objects.create(name=name) for name in names]
        lower_vip = CallCenterLeadGroup.objects.create(name='vip')
        self.lead_one.group = sources[0]
        self.lead_one.save(update_fields=['group'])
        self.lead_two.group = lower_vip
        self.lead_two.save(update_fields=['group'])
        before = ReferralLead.objects.count()

        merge_doctor(apps, None)

        self.lead_one.refresh_from_db()
        self.lead_two.refresh_from_db()
        self.assertEqual(ReferralLead.objects.count(), before)
        self.assertEqual(self.lead_one.group_id, doctor.pk)
        self.assertEqual(self.lead_two.group_id, vip.pk)
        self.assertFalse(CallCenterLeadGroup.objects.filter(pk__in=[s.pk for s in sources]+[lower_vip.pk]).exists())
        self.assertEqual(AuditLog.objects.filter(action='call_center_group_merge',path='migration:0110').count(), 4)

    def test_group_creation_reuses_existing_doctor_and_vip_groups(self):
        self.operator_one.is_superuser = True
        self.operator_one.save(update_fields=['is_superuser'])
        before = CallCenterLeadGroup.objects.count()
        for name in ['مزوهای قدیمی آقای دکتر', 'vip']:
            result = self.client.post(reverse('call_center_group_create'), {'name': name})
            self.assertEqual(result.status_code, 302)
        self.assertEqual(CallCenterLeadGroup.objects.count(), before)
