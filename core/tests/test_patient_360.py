from datetime import time
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    BodyAnalysisRecord, Branch, EmployeeProfile, FinancialTransaction, PatientDietProgram,
    PatientProfile, PatientTeamRating, ReferralLead, ReferralProfile, SmsMessageLog, VisitAppointment,
)


class Patient360Tests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='Patient 360 Test')
        self.user=User.objects.create_user('patient360-consultant',password='pass')
        profile=self.user.profile
        profile.role='consultant'
        profile.branch=self.branch
        profile.is_active=True
        profile.save(update_fields=['role','branch','is_active'])

        source_user=User.objects.create_user('patient360-source',password='x')
        self.source=ReferralProfile.objects.create(
            user=source_user,referral_code='P360SRC',is_active=True,
        )
        self.lead=ReferralLead.objects.create(
            referrer=self.source,full_name='بیمار تست',phone='09121112233',
            status='contacted',contact_result='follow_up',
        )
        self.appt=VisitAppointment.objects.create(
            lead=self.lead,branch=self.branch,full_name='بیمار تست',phone='09121112233',
            appointment_date=timezone.localdate(),appointment_time=time(10,0),
            status='arrived',source='call_center',created_by=self.user,
        )
        self.client.force_login(self.user)

    def test_from_appointment_creates_profile_and_redirects(self):
        response=self.client.get(reverse('patient_360_from_appointment',args=[self.appt.pk]))
        self.assertEqual(response.status_code,302)
        patient=PatientProfile.objects.get(phone='09121112233')
        self.assertEqual(response['Location'],reverse('patient_360',args=[patient.pk]))

    def test_phone_variants_reuse_existing_profile_without_duplicate(self):
        patient=PatientProfile.objects.create(
            full_name='بیمار قدیمی',phone='+989121112233',home_branch=self.branch,
        )
        response=self.client.get(reverse('patient_360_from_appointment',args=[self.appt.pk]))
        self.assertEqual(response.status_code,302)
        self.assertEqual(PatientProfile.objects.count(),1)
        patient.refresh_from_db()
        self.assertEqual(patient.phone,'09121112233')

    def test_consultant_sees_masked_phone_and_not_full_number(self):
        patient=PatientProfile.objects.create(
            full_name='بیمار خصوصی',phone='09121112233',home_branch=self.branch,
        )
        response=self.client.get(reverse('patient_360',args=[patient.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'0912***2233')
        self.assertNotContains(response,'09121112233')
        self.assertEqual(response['Cache-Control'],'no-store, private')

    @patch('core.patient_360_views.send_sms')
    def test_consultant_can_send_sms_without_phone_in_request(self,mocked_send):
        patient=PatientProfile.objects.create(
            full_name='بیمار خصوصی',phone='09121112233',home_branch=self.branch,
        )
        response=self.client.post(
            reverse('patient_360_send_sms',args=[patient.pk]),
            {'body':'پیام تست محرمانه'},
        )
        self.assertEqual(response.status_code,302)
        mocked_send.assert_called_once()
        args,kwargs=mocked_send.call_args
        self.assertEqual(args[0],'09121112233')
        self.assertEqual(args[1],'پیام تست محرمانه')
        self.assertEqual(kwargs['created_by'],self.user)

    def test_profile_aggregates_finance_sms_and_clinical_history(self):
        patient=PatientProfile.objects.create(
            full_name='بیمار تست',phone='09121112233',home_branch=self.branch,
        )
        FinancialTransaction.objects.create(
            source='manual',branch=self.branch,appointment=self.appt,
            occurred_at=timezone.now(),amount=Decimal('2500000'),entry_type='inc',
            review_status='approved',recorded_by=self.user,
        )
        SmsMessageLog.objects.create(
            number='09121112233',body='پیام تست',purpose='appointment',
            status='accepted',appointment=self.appt,created_by=self.user,
        )
        PatientDietProgram.objects.create(
            patient=patient,appointment=self.appt,diet_name='رژیم تست',
            recommendation_pack='آب و فیبر',prescribed_by=self.user,
        )
        BodyAnalysisRecord.objects.create(
            patient=patient,weight_kg=Decimal('81.2'),bmi=Decimal('27.1'),
            recorded_by=self.user,
        )

        response=self.client.get(reverse('patient_360',args=[patient.pk]))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.context['approved_paid'],Decimal('2500000'))
        self.assertContains(response,'رژیم تست')
        self.assertContains(response,'پیام تست')
        self.assertContains(response,'81.2')
        self.assertEqual(response.context['appointment_count'],1)
        self.assertEqual(response.context['recorded_contact_count'],1)
        self.assertEqual(len(response.context['visit_rows']),1)
        self.assertEqual(response.context['visit_rows'][0]['food'],'رژیم تست')
        self.assertIn('آب و فیبر',response.context['visit_rows'][0]['recommendations'])

    def test_staff_can_save_shared_patient_rating(self):
        patient=PatientProfile.objects.create(
            full_name='بیمار امتیاز',phone='09123334455',home_branch=self.branch,
        )
        response=self.client.post(
            reverse('patient_360_rating',args=[patient.pk]),
            {
                'overall_score':'5',
                'cooperation_score':'4',
                'purchase_capacity_score':'3',
                'tags':'خوش‌برخورد، منظم',
                'note':'برای نوبت بعدی صبح تماس شود.',
            },
        )
        self.assertEqual(response.status_code,302)
        rating=PatientTeamRating.objects.get(patient=patient,author=self.user)
        self.assertEqual(rating.overall_score,5)
        self.assertEqual(rating.cooperation_score,4)
        self.assertEqual(rating.purchase_capacity_score,3)
        page=self.client.get(reverse('patient_360',args=[patient.pk]))
        self.assertContains(page,'ارزیابی تیم از بیمار')
        self.assertContains(page,'خوش‌برخورد')

    def test_receptionist_can_upload_patient_photo(self):
        receptionist=User.objects.create_user('p360-receptionist',password='pass')
        profile=receptionist.profile
        profile.role='receptionist'
        profile.branch=self.branch
        profile.save(update_fields=['role','branch'])
        patient=PatientProfile.objects.create(
            full_name='بیمار عکس',phone='09125556677',home_branch=self.branch,
        )
        self.client.force_login(receptionist)
        # Minimal PNG signature is sufficient for upload-path behavior; image
        # decoding is handled by storage/browser display, not this endpoint.
        photo=SimpleUploadedFile('patient.png',b'\x89PNG\r\n\x1a\n',content_type='image/png')
        response=self.client.post(
            reverse('patient_360_photo',args=[patient.pk]),
            {'photo':photo},
        )
        self.assertEqual(response.status_code,302)
        patient.refresh_from_db()
        self.assertTrue(bool(patient.photo))

    def test_call_center_can_rate_only_assigned_lead_patient(self):
        operator=User.objects.create_user('p360-call-center',password='pass')
        operator_profile=operator.profile
        operator_profile.role='call_center'
        operator_profile.branch=None
        operator_profile.save(update_fields=['role','branch'])
        self.lead.assigned_to=operator_profile
        self.lead.save(update_fields=['assigned_to'])
        self.client.force_login(operator)

        response=self.client.get(reverse('patient_360_from_lead',args=[self.lead.pk]))
        self.assertEqual(response.status_code,302)
        patient=PatientProfile.objects.get(phone='09121112233')
        rating_response=self.client.post(
            reverse('patient_360_rating',args=[patient.pk]),
            {'overall_score':'4','cooperation_score':'5','purchase_capacity_score':'2'},
        )
        self.assertEqual(rating_response.status_code,302)
        self.assertTrue(PatientTeamRating.objects.filter(patient=patient,author=operator).exists())

        other=PatientProfile.objects.create(full_name='غریبه',phone='09129998877')
        denied=self.client.get(reverse('patient_360',args=[other.pk]))
        self.assertEqual(denied.status_code,403)

