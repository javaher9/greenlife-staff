from datetime import time
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    BodyAnalysisRecord,
    Branch,
    PatientDeviceProgram,
    PatientProfile,
    ReferralLead,
    ReferralProfile,
    StaffNotification,
    VisitAppointment,
)


class DoctorDashboardTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='نیاوران تست')
        self.other_branch=Branch.objects.create(name='پونک تست')

        self.doctor_user=User.objects.create_user(
            username='doctor-test',
            first_name='پزشک',
            last_name='تست',
            password='StrongPass123',
        )
        self.doctor=self.doctor_user.profile
        self.doctor.role='doctor'
        self.doctor.branch=self.branch
        self.doctor.is_active=True
        self.doctor.save(update_fields=['role','branch','is_active'])

        self.operator_user=User.objects.create_user(
            username='salehi-doctor-test',
            first_name='محمد',
            last_name='صالحی',
            password='StrongPass123',
        )
        self.operator=self.operator_user.profile
        self.operator.role='call_center'
        self.operator.branch=self.branch
        self.operator.is_active=True
        self.operator.save(update_fields=['role','branch','is_active'])

        self.consultant_user=User.objects.create_user(
            username='consultant-doctor-test',
            first_name='مشاور',
            last_name='تست',
            password='StrongPass123',
        )
        self.consultant=self.consultant_user.profile
        self.consultant.role='consultant'
        self.consultant.branch=self.branch
        self.consultant.is_active=True
        self.consultant.save(update_fields=['role','branch','is_active'])

        source_user=User.objects.create_user(username='doctor-source',password='StrongPass123')
        self.source=ReferralProfile.objects.create(
            user=source_user,
            referral_code='GLDOCTORTEST',
            is_active=True,
        )
        self.lead=ReferralLead.objects.create(
            referrer=self.source,
            full_name='مریم حسینی',
            phone='09121234567',
            status='appointment',
            source='panel',
            assigned_to=self.operator,
            first_appointment_by=self.operator_user,
        )
        self.appointment=VisitAppointment.objects.create(
            lead=self.lead,
            branch=self.branch,
            full_name='مریم حسینی',
            phone='09121234567',
            service='کنترل وزن',
            appointment_date=timezone.localdate(),
            appointment_time=time(10,0),
            status='arrived',
            source='call_center',
            created_by=self.operator_user,
        )
        VisitAppointment.objects.create(
            branch=self.other_branch,
            full_name='بیمار شعبه دیگر',
            phone='09129999999',
            service='کنترل وزن',
            appointment_date=timezone.localdate(),
            appointment_time=time(10,15),
            status='booked',
            source='receptionist',
        )
        self.client.login(username='doctor-test',password='StrongPass123')

    def test_doctor_dashboard_routes_by_device(self):
        desktop=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        )
        self.assertEqual(desktop.status_code,302)
        self.assertEqual(desktop.url,reverse('doctor_dashboard'))

        mobile=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 16; Mobile) AppleWebKit/537.36',
        )
        self.assertEqual(mobile.status_code,200)
        self.assertTemplateUsed(mobile,'core/dashboard.html')
        self.assertEqual(mobile.context['role'],'doctor')
        self.assertContains(mobile,'حضور')

    def test_doctor_sees_only_own_branch_and_phone_is_hidden(self):
        response=self.client.get(reverse('doctor_dashboard'))
        self.assertEqual(response.status_code,200)
        body=response.content.decode('utf-8')
        self.assertIn('مریم حسینی',body)
        self.assertIn('خورشیدی',body)
        self.assertNotIn('بیمار شعبه دیگر',body)
        self.assertNotIn('09121234567',body)

    def test_doctor_only_sees_checked_in_patients(self):
        waiting=VisitAppointment.objects.create(
            branch=self.branch,
            full_name='بیمار هنوز پذیرش نشده',
            phone='09127778888',
            service='کنترل وزن',
            appointment_date=timezone.localdate(),
            appointment_time=time(11,0),
            status='booked',
            care_stage='doctor',
            source='call_center',
            created_by=self.operator_user,
        )
        response=self.client.get(reverse('doctor_dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'مریم حسینی')
        self.assertContains(response,'بیمار هنوز پذیرش نشده')
        self.assertContains(response,'ثبت‌شده · پذیرش نشده')
        self.assertEqual(len(response.context['appointment_rows']),2)

        blocked=self.client.post(reverse('doctor_dashboard'),{
            'appointment_id':waiting.pk,
            'action':'send_to_consultant',
        })
        self.assertEqual(blocked.status_code,302)
        waiting.refresh_from_db()
        self.assertEqual(waiting.status,'booked')
        self.assertEqual(waiting.care_stage,'doctor')

    def test_doctor_queue_shows_patient_avatar_and_light_theme(self):
        patient=PatientProfile.objects.create(
            full_name='مریم حسینی',
            phone='09121234567',
            home_branch=self.branch,
        )
        patient.photo=SimpleUploadedFile(
            'patient-avatar.png',b'\x89PNG\r\n\x1a\n',content_type='image/png'
        )
        patient.save(update_fields=['photo','updated_at'])
        response=self.client.get(reverse('doctor_dashboard'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'patient-mini-avatar')
        self.assertContains(response,patient.photo.url)
        self.assertContains(response,'Light clinical desktop theme')
        self.assertContains(response,'#f3f7f5')

    def test_patient_profile_is_created_and_analysis_trends_render(self):
        self.client.get(reverse('doctor_dashboard'))
        patient=PatientProfile.objects.get(phone='09121234567')
        patient.height_cm=Decimal('165.0')
        patient.neighborhood='نیاوران'
        patient.save(update_fields=['height_cm','neighborhood','updated_at'])
        BodyAnalysisRecord.objects.create(
            patient=patient,
            weight_kg=Decimal('78.0'),
            visceral_fat=Decimal('12.0'),
            inbody_score=Decimal('66.0'),
            skeletal_muscle_kg=Decimal('29.0'),
            body_fat_percent=Decimal('37.0'),
            recorded_by=self.doctor_user,
        )
        BodyAnalysisRecord.objects.create(
            patient=patient,
            weight_kg=Decimal('72.0'),
            visceral_fat=Decimal('9.0'),
            inbody_score=Decimal('75.0'),
            skeletal_muscle_kg=Decimal('31.2'),
            body_fat_percent=Decimal('31.0'),
            recorded_by=self.doctor_user,
        )
        response=self.client.get(reverse('doctor_dashboard'),{'appointment':self.appointment.pk})
        body=response.content.decode('utf-8')
        self.assertIn('امتیاز آنالیز',body)
        self.assertIn('چربی احشایی',body)
        self.assertIn('31.2',body)
        self.assertIn('نیاوران',body)

    def test_repeat_visit_reuses_same_patient_360_and_tracks_visit_number(self):
        first_patient=PatientProfile.objects.create(
            full_name='مریم حسینی',
            phone='+989121234567',
            home_branch=self.branch,
        )
        previous=VisitAppointment.objects.create(
            branch=self.branch,
            full_name='مریم حسینی',
            phone='09121234567',
            service='ویزیت قبلی',
            appointment_date=timezone.localdate()-timezone.timedelta(days=30),
            appointment_time=time(9,30),
            status='completed',
            source='receptionist',
            created_by=self.operator_user,
        )
        response=self.client.get(
            reverse('doctor_dashboard'),
            {'appointment':self.appointment.pk},
        )
        self.assertEqual(response.status_code,200)
        self.assertEqual(PatientProfile.objects.count(),1)
        first_patient.refresh_from_db()
        self.assertEqual(first_patient.phone,'09121234567')
        self.assertEqual(response.context['selected_visit_number'],2)
        visit_ids=[row['appointment'].pk for row in response.context['patient_visit_rows']]
        self.assertIn(previous.pk,visit_ids)
        self.assertIn(self.appointment.pk,visit_ids)
        self.assertContains(response,'ویزیت 2')
        self.assertContains(response,'پرونده یکپارچه 360°')

    def test_doctor_can_add_device_program_from_same_page(self):
        self.client.get(reverse('doctor_dashboard'))
        response=self.client.post(reverse('doctor_dashboard'),{
            'appointment_id':self.appointment.pk,
            'action':'device',
            'device_name':'Double Define',
            'area':'شکم و پهلو',
            'sessions':'4',
        },follow=True)
        self.assertEqual(response.status_code,200)
        patient=PatientProfile.objects.get(phone='09121234567')
        item=PatientDeviceProgram.objects.get(patient=patient)
        self.assertEqual(item.device_name,'Double Define')
        self.assertEqual(item.sessions_prescribed,4)
        self.assertEqual(item.prescribed_by,self.doctor_user)
        self.assertEqual(item.appointment,self.appointment)

    def test_end_visit_sends_patient_to_consultant_queue(self):
        self.client.get(reverse('doctor_dashboard'))
        self.client.post(reverse('doctor_dashboard'),{
            'appointment_id':self.appointment.pk,
            'action':'device',
            'device_name':'Double Define',
            'area':'شکم و پهلو',
            'sessions':'4',
        })
        response=self.client.post(reverse('doctor_dashboard'),{
            'appointment_id':self.appointment.pk,
            'action':'send_to_consultant',
        },follow=True)
        self.assertEqual(response.status_code,200)

        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.care_stage,'consultant')
        self.assertEqual(self.appointment.doctor_completed_by,self.doctor_user)
        self.assertIsNotNone(self.appointment.doctor_completed_at)
        self.assertTrue(
            StaffNotification.objects.filter(
                user=self.consultant_user,
                notification_type='doctor_handoff',
            ).exists()
        )

        self.client.logout()
        self.client.login(username='consultant-doctor-test',password='StrongPass123')
        dashboard=self.client.get(reverse('dashboard'))
        self.assertRedirects(
            dashboard,
            reverse('consultant_sales_outcomes'),
            fetch_redirect_response=False,
        )
        workspace=self.client.get(reverse('consultant_sales_outcomes'))
        self.assertEqual(workspace.status_code,200)
        body=workspace.content.decode('utf-8')
        self.assertIn('مریم حسینی',body)
        self.assertIn('Double Define',body)

    def test_doctor_rejects_missing_or_unknown_patient_id(self):
        before=PatientDeviceProgram.objects.count()
        for appointment_id in ('', '99999999'):
            response=self.client.post(reverse('doctor_action_api'), {
                'action':'device', 'appointment_id':appointment_id,
                'device_name':'Double Define','sessions':'4',
            })
            self.assertEqual(response.status_code,400)
            self.assertFalse(response.json()['ok'])
        self.assertEqual(PatientDeviceProgram.objects.count(),before)

    def test_doctor_daily_stats_count_booked_and_cancelled(self):
        VisitAppointment.objects.create(
            branch=self.branch, full_name='لغو شده',phone='09121239991',
            appointment_date=timezone.localdate(),appointment_time=time(11,0),
            status='cancelled',source='receptionist',
        )
        VisitAppointment.objects.create(
            branch=self.branch, full_name='رزرو جدید',phone='09121239992',
            appointment_date=timezone.localdate(),appointment_time=time(11,15),
            status='booked',source='receptionist',
        )
        response=self.client.get(reverse('doctor_dashboard'))
        stats=response.context['appointment_stats']
        self.assertEqual(stats['total'],2)
        self.assertEqual(stats['arrived'],1)
        self.assertEqual(stats['cancelled'],1)

    def test_doctor_api_creates_plan_and_keeps_handoff_visible(self):
        response=self.client.post(reverse('doctor_action_api'), {
            'action':'device','appointment_id':self.appointment.pk,
            'device_name':'Double Define','sessions':'4',
        })
        self.assertEqual(response.status_code,200)
        self.assertTrue(response.json()['ok'])
        finish=self.client.post(reverse('doctor_action_api'),{
            'action':'send_to_consultant','appointment_id':self.appointment.pk,
        })
        self.assertEqual(finish.status_code,200)
        response=self.client.get(reverse('doctor_dashboard'))
        self.assertIn(self.appointment.pk,[x['item'].pk for x in response.context['appointment_rows']])
        self.assertEqual(response.context['appointment_stats']['sent'],1)
