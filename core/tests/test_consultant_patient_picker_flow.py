from datetime import time

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Branch, PatientProfile, VisitAppointment


class ConsultantPatientPickerFlowTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='نیاوران تست',is_active=True)
        self.user=User.objects.create_user('consultant-picker',password='pass')
        profile=self.user.profile
        profile.role='consultant'
        profile.branch=self.branch
        profile.is_active=True
        profile.save(update_fields=['role','branch','is_active'])
        self.client.force_login(self.user)

    def test_appointment_without_plan_still_appears_in_picker(self):
        appointment=VisitAppointment.objects.create(
            branch=self.branch,
            full_name='بیمار بدون پکیج',
            phone='09120001122',
            appointment_date=timezone.localdate(),
            appointment_time=time(10,15),
            source='receptionist',
            created_by=self.user,
        )
        response=self.client.get(reverse('device_booking_schedule'))
        self.assertEqual(response.status_code,200)
        options=response.context['patient_options']
        self.assertTrue(any(item['appointment_id']==appointment.pk for item in options))
        self.assertContains(response,'بدون پکیج')

    def test_quick_patient_creates_canonical_profile_without_fake_appointment(self):
        before=VisitAppointment.objects.count()
        response=self.client.post(
            reverse('device_booking_schedule'),
            {
                'action':'quick_patient',
                'branch':str(self.branch.pk),
                'full_name':'بیمار ثبت سریع',
                'phone':'09123334455',
            },
        )
        self.assertEqual(response.status_code,302)
        patient=PatientProfile.objects.get(phone='09123334455')
        self.assertEqual(patient.full_name,'بیمار ثبت سریع')
        self.assertEqual(patient.home_branch_id,self.branch.pk)
        self.assertEqual(VisitAppointment.objects.count(),before)
        self.assertEqual(response['Location'],reverse('patient_360',args=[patient.pk]))
