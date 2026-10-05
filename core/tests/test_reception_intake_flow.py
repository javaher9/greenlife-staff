from datetime import time
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import BodyAnalysisRecord, Branch, EmployeeProfile, VisitAppointment


class ReceptionIntakeFlowTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='شعبه تست پذیرش')
        self.reception=User.objects.create_user(username='reception-test',password='pass12345')
        EmployeeProfile.objects.create(user=self.reception,role='receptionist',branch=self.branch)
        self.doctor=User.objects.create_user(username='doctor-test',password='pass12345')
        EmployeeProfile.objects.create(user=self.doctor,role='doctor',branch=self.branch)
        self.appointment=VisitAppointment.objects.create(
            branch=self.branch,full_name='بیمار تست',phone='09121234567',
            appointment_date=timezone.localdate(),appointment_time=time(10,0),
            status='booked',care_stage='doctor',source='receptionist',
            created_by=self.reception,
        )

    def test_arrival_status_redirects_to_required_intake(self):
        self.client.force_login(self.reception)
        response=self.client.post(
            reverse('receptionist_appointment_status',args=[self.appointment.pk,'arrived'])
        )
        self.assertRedirects(
            response,reverse('receptionist_appointment_intake',args=[self.appointment.pk])
        )
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status,'booked')

    def test_complete_intake_records_analysis_then_sends_to_doctor(self):
        self.client.force_login(self.reception)
        response=self.client.post(
            reverse('receptionist_appointment_intake',args=[self.appointment.pk]),
            {
                'height_cm':'170','weight_kg':'80','inbody_score':'72',
                'visceral_fat':'11','body_fat_percent':'31.5',
                'skeletal_muscle_kg':'29.4','waist_cm':'98',
            },
        )
        self.assertRedirects(response,reverse('dashboard'))
        self.appointment.refresh_from_db()
        self.assertEqual(self.appointment.status,'arrived')
        self.assertEqual(self.appointment.care_stage,'doctor')
        analysis=BodyAnalysisRecord.objects.get(patient__phone='09121234567')
        self.assertEqual(analysis.weight_kg,Decimal('80'))
        self.assertEqual(analysis.measurements['waist_cm'],98.0)
        self.assertEqual(analysis.patient.height_cm,Decimal('170'))

    def test_doctor_keeps_seen_and_unseen_today_in_list(self):
        seen=VisitAppointment.objects.create(
            branch=self.branch,full_name='ویزیت شده',phone='09120000001',
            appointment_date=timezone.localdate(),appointment_time=time(10,15),
            status='arrived',care_stage='consultant',source='receptionist',
            created_by=self.reception,doctor_completed_by=self.doctor,
            doctor_completed_at=timezone.now(),
        )
        self.appointment.status='arrived'
        self.appointment.save(update_fields=['status','updated_at'])
        self.client.force_login(self.doctor)
        response=self.client.get(reverse('doctor_dashboard'))
        self.assertEqual(response.status_code,200)
        rows=response.context['appointment_rows']
        ids={row['item'].pk for row in rows}
        self.assertIn(self.appointment.pk,ids)
        self.assertIn(seen.pk,ids)
