import json
from datetime import time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.bulk_sms_audiences import _iran_number, audience_preview, catalog
from core.models import (
    Branch, CallCenterLeadGroup, Country, EmployeeProfile,
    PatientDeviceProgram, PatientProfile, ReferralLead,
    ReferralProfile, SmsMessageLog, VisitAppointment,
)


class BulkSmsAudienceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.country=Country.objects.get_or_create(
            code='IR',
            defaults={'name_english':'Iran','name_local':'ایران'},
        )[0]
        cls.branch=Branch.objects.create(name='نیاوران انبوه',country=cls.country)
        cls.admin=User.objects.create_superuser('bulk-admin','bulk@example.com','pass')
        cls.employee=User.objects.create_user('bulk-employee',password='pass')
        EmployeeProfile.objects.filter(user=cls.employee).update(
            role='receptionist',is_active=True,branch=cls.branch,
        )
        cls.ref_user=User.objects.create_user('bulk-referrer',password='pass')
        cls.ref=ReferralProfile.objects.create(
            user=cls.ref_user,referral_code='BULKREF001',
            phone='09121112233',
        )
        cls.group=CallCenterLeadGroup.objects.create(name='پیگیری ویژه تست')
        cls.lead=ReferralLead.objects.create(
            referrer=cls.ref,country=cls.country,
            full_name='مخاطب نمونه',phone='09121112233',
            status='new',group=cls.group,
            notes='اینستاگرام - دستی | [instagram_page:greenlife]',
            source='panel',
        )
        cls.patient=PatientProfile.objects.create(
            full_name='همین شخص',phone='+989121112233',
            home_branch=cls.branch,is_vip=True,
        )
        cls.device=PatientDeviceProgram.objects.create(
            patient=cls.patient,device_name='Cooltech Define',
        )
        cls.visit=VisitAppointment.objects.create(
            branch=cls.branch,full_name='مخاطب نمونه',
            phone='09121112233',lead=cls.lead,
            appointment_date=timezone.localdate(),
            appointment_time=time(14,0),status='no_show',
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_live_catalog_includes_dynamic_devices_branches_and_call_center_groups(self):
        keys={item['key'] for item in catalog()}
        self.assertIn('device:Cooltech Define',keys)
        self.assertIn('leadgroup:'+str(self.group.pk),keys)
        self.assertIn('branch_leads:'+str(self.branch.pk),keys)
        self.assertIn('lead_instagram_manual',keys)
        self.assertIn('visit_no_show',keys)
        self.assertIn('network_all',keys)

    def test_multiple_segments_deduplicate_and_mask_phone(self):
        before=SmsMessageLog.objects.count()
        preview=audience_preview([
            'lead_all','patient_vip','visit_no_show','device:Cooltech Define',
        ])
        self.assertEqual(preview['count'],1)
        self.assertEqual(preview['selected_groups'],4)
        self.assertIn('0912***2233',preview['sample_masked'])
        self.assertNotIn('09121112233',str(preview))
        self.assertEqual(SmsMessageLog.objects.count(),before)

    def test_group_api_preview_never_sends(self):
        response=self.client.post(
            reverse('bulk_sms_preview_api'),
            data=json.dumps({'segments':['lead_instagram_manual','network_all']}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['ok'])
        self.assertEqual(response.json()['count'],1)
        self.assertEqual(SmsMessageLog.objects.count(),0)

    def test_page_has_menu_and_grouping(self):
        response=self.client.get(reverse('bulk_sms_groups'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'ارسال پیامک گروهی')
        self.assertContains(response,'Cooltech Define')
        self.assertEqual(response['Cache-Control'],'no-store, private')

    def test_unauthorized_staff_cannot_access_private_audiences(self):
        self.client.force_login(self.employee)
        page=self.client.get(reverse('bulk_sms_groups'))
        preview=self.client.post(
            reverse('bulk_sms_preview_api'),
            data=json.dumps({'segments':['patient_vip']}),
            content_type='application/json',
        )
        self.assertEqual(page.status_code,403)
        self.assertEqual(preview.status_code,403)

    def test_bad_or_duplicate_segment_codes_are_rejected(self):
        for keys in ([],['unknown'],['lead_all','lead_all']):
            response=self.client.post(
                reverse('bulk_sms_preview_api'),
                data=json.dumps({'segments':keys}),
                content_type='application/json',
            )
            self.assertEqual(response.status_code,400)

    def test_iran_number_normalizes_legacy_formats(self):
        self.assertEqual(_iran_number('+98 912 111 2233'),'09121112233')
        self.assertEqual(_iran_number('۹۱۲۱۱۱۲۲۳۳'),'09121112233')
        self.assertEqual(_iran_number('02134247'),'')
