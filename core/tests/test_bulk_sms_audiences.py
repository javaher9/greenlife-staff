import json
from datetime import time, timedelta

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
        self.assertIn('no-store',response['Cache-Control'])

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

    def test_compound_all_requires_same_phone_in_every_selected_group(self):
        # One contact may be in many independent tables; no duplicates.
        response=self.client.post(
            reverse('bulk_sms_preview_api'),
            data=json.dumps({'segments':['lead_instagram_manual','visit_no_show','patient_vip'],
                'combine':'all','date_filter':{'preset':'all'}}),
            content_type='application/json',
        )
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['count'],1)
        self.assertEqual(response.json()['combine'],'all')
        self.assertIsNone(response.json()['date_filter'])

        # Move the visit into a different status: intersection is now empty,
        # while union still finds the lead and patient.
        VisitAppointment.objects.filter(pk=self.visit.pk).update(status='booked')
        self.assertEqual(audience_preview(
            ['lead_instagram_manual','visit_no_show','patient_vip'],combine='all',
        )['count'],0)
        self.assertEqual(audience_preview(
            ['lead_instagram_manual','visit_no_show','patient_vip'],combine='any',
        )['count'],1)

    def test_visit_window_filters_event_not_vip_registration(self):
        # The patient existed long before the appointment, but should still
        # qualify for VIP AND recent visit.
        PatientProfile.objects.filter(pk=self.patient.pk).update(
            created_at=timezone.now()-timedelta(days=600)
        )
        keys=['patient_vip','visit_no_show']
        recent={'preset':'7','event':'visit'}
        result=audience_preview(keys,combine='all',date_filter=recent)
        self.assertEqual(result['count'],1)
        self.assertEqual(result['date_filter']['event'],'visit')
        VisitAppointment.objects.filter(pk=self.visit.pk).update(
            appointment_date=timezone.localdate()-timedelta(days=90)
        )
        self.assertEqual(audience_preview(keys,combine='all',date_filter=recent)['count'],0)
        self.assertEqual(audience_preview(keys,combine='all',date_filter={'preset':'all'})['count'],1)

    def test_lead_windows_work_independently_of_visit_dates(self):
        keys=['lead_instagram_manual','patient_vip']
        recent={'preset':'30','event':'lead'}
        self.assertEqual(audience_preview(keys,combine='all',date_filter=recent)['count'],1)
        ReferralLead.objects.filter(pk=self.lead.pk).update(
            created_at=timezone.now()-timedelta(days=400)
        )
        self.assertEqual(audience_preview(keys,combine='all',date_filter=recent)['count'],0)
        self.assertEqual(audience_preview(keys,combine='all',date_filter={'preset':'all'})['count'],1)

    def test_device_time_filter_binds_date_to_correct_device(self):
        PatientDeviceProgram.objects.filter(pk=self.device.pk).update(
            prescribed_at=timezone.now()-timedelta(days=90)
        )
        PatientDeviceProgram.objects.create(patient=self.patient,device_name='EM Sculpt')
        result=audience_preview(['device:Cooltech Define'],date_filter={
            'preset':'7','event':'service',
        })
        self.assertEqual(result['count'],0)
        self.assertEqual(audience_preview(['device:EM Sculpt'],date_filter={
            'preset':'7','event':'service',
        })['count'],1)

    def test_date_window_validations_and_no_unexpected_sending(self):
        before=SmsMessageLog.objects.count()
        for invalid in (
            {'preset':'7','event':'invalid'},
            {'preset':'custom','event':'visit','from':'2026-01-12','to':'2026-01-01'},
            {'preset':'custom','event':'visit','from':'broken','to':'2026-01-01'},
            {'preset':'custom','event':'visit','from':'2010-01-01','to':'2026-01-01'},
        ):
            response=self.client.post(reverse('bulk_sms_preview_api'),data=json.dumps({
                'segments':['visit_no_show'],'combine':'all','date_filter':invalid
            }),content_type='application/json')
            self.assertEqual(response.status_code,400)
        mismatch=self.client.post(reverse('bulk_sms_preview_api'),data=json.dumps({
            'segments':['patient_vip'],'date_filter':{'preset':'7','event':'visit'}
        }),content_type='application/json')
        self.assertEqual(mismatch.status_code,400)
        bad_mode=self.client.post(reverse('bulk_sms_preview_api'),data=json.dumps({
            'segments':['visit_no_show'],'combine':'xor'
        }),content_type='application/json')
        self.assertEqual(bad_mode.status_code,400)
        self.assertEqual(SmsMessageLog.objects.count(),before)

    def test_custom_window_and_previous_month_are_inclusive(self):
        current=timezone.localdate()
        custom={
            'preset':'custom','event':'visit',
            'from':current.isoformat(),'to':current.isoformat(),
        }
        self.assertEqual(audience_preview(['visit_no_show'],date_filter=custom)['count'],1)
        self.assertEqual(audience_preview(['visit_no_show'],date_filter={
            'preset':'previous_month','event':'visit',
        })['count'],0)

    def test_ui_has_compound_and_zero_time_choices(self):
        response=self.client.get(reverse('bulk_sms_groups'))
        self.assertContains(response,'id="bulk-combine"')
        self.assertContains(response,'value="all">همه شرط‌ها')
        self.assertContains(response,'id="bulk-date-preset"')
        self.assertContains(response,'0 — همه تاریخ‌ها')
        self.assertContains(response,'id="bulk-date-from"')
        self.assertContains(response,'id="bulk-date-to"')
