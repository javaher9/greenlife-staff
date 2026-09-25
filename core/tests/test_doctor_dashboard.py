from datetime import time
from decimal import Decimal

from django.contrib.auth.models import User
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

    def test_doctor_sees_only_own_branch_and_phone_is_hidden(self):
        response=self.client.get(reverse('doctor_dashboard'))
        self.assertEqual(response.status_code,200)
        body=response.content.decode('utf-8')
        self.assertIn('مریم حسینی',body)
        self.assertIn('خورشیدی',body)
        self.assertNotIn('بیمار شعبه دیگر',body)
        self.assertNotIn('09121234567',body)

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
