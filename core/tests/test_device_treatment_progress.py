from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    Branch, ConsultationPlan, ConsultationPlanItem, DeviceCabin, DeviceSessionBooking,
    DeviceTypeSchedule, PatientDeviceProgram, PatientProfile, PhysicalDevice, VisitAppointment,
)


class DeviceTreatmentProgressTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='Treatment Progress Test')
        self.user=User.objects.create_user('progress-consultant',password='pass')
        profile=self.user.profile
        profile.role='consultant'
        profile.branch=self.branch
        profile.is_active=True
        profile.save(update_fields=['role','branch','is_active'])
        self.client.force_login(self.user)

        self.patient=PatientProfile.objects.create(
            full_name='بیمار روند',phone='09121110000',home_branch=self.branch,
        )
        self.appointment=VisitAppointment.objects.create(
            branch=self.branch,full_name='بیمار روند',phone='09121110000',
            appointment_date=timezone.localdate(),
            appointment_time=timezone.localtime().time().replace(second=0,microsecond=0),
            status='arrived',source='receptionist',created_by=self.user,
        )
        self.program=PatientDeviceProgram.objects.create(
            patient=self.patient,appointment=self.appointment,
            device_name='Double Define',area='شکم و پهلو',
            sessions_prescribed=2,prescribed_by=self.user,
        )
        self.plan=ConsultationPlan.objects.create(
            appointment=self.appointment,consultant=self.user,status='paid',
        )
        self.item=ConsultationPlanItem.objects.create(
            plan=self.plan,kind='device',source='doctor',source_pk=self.program.pk,
            title='Double Define',area='شکم و پهلو',quantity=2,included=True,
        )
        self.kind=DeviceTypeSchedule.objects.create(
            code='PROGRESS1',name='Progress Device',
            treatment_minutes=30,preparation_minutes=10,
        )
        self.cabin=DeviceCabin.objects.create(branch=self.branch,name='__TEST_PROGRESS')
        self.device=PhysicalDevice.objects.create(
            branch=self.branch,device_type=self.kind,name='PROGRESS-DEVICE',
            cabin=self.cabin,
        )

    def _booking(self,minutes):
        start=timezone.now()+timedelta(minutes=minutes)
        return DeviceSessionBooking.objects.create(
            branch=self.branch,appointment=self.appointment,plan_item=self.item,
            cabin=self.cabin,device=self.device,
            starts_at=start,treatment_ends_at=start+timedelta(minutes=30),
            blocked_until=start+timedelta(minutes=40),
            treatment_minutes_snapshot=30,preparation_minutes_snapshot=10,
            created_by=self.user,
        )

    def test_completed_sessions_update_patient_program_and_plan_snapshot(self):
        first=self._booking(60)
        response=self.client.post(reverse('device_booking_status',args=[first.pk,'completed']))
        self.assertEqual(response.status_code,302)

        self.program.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.program.sessions_completed,1)
        self.assertEqual(self.program.status,'active')
        self.assertEqual(self.item.doctor_snapshot['treatment_sessions_completed'],1)
        self.assertEqual(self.item.doctor_snapshot['treatment_sessions_remaining'],1)
        self.assertEqual(self.item.doctor_snapshot['treatment_status'],'active')

        second=self._booking(120)
        self.client.post(reverse('device_booking_status',args=[second.pk,'completed']))
        self.program.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.program.sessions_completed,2)
        self.assertEqual(self.program.status,'completed')
        self.assertEqual(self.item.doctor_snapshot['treatment_status'],'completed')
        self.assertEqual(self.item.doctor_snapshot['treatment_sessions_remaining'],0)

    def test_correcting_completed_status_recalculates_without_double_count(self):
        booking=self._booking(60)
        self.client.post(reverse('device_booking_status',args=[booking.pk,'completed']))
        self.client.post(reverse('device_booking_status',args=[booking.pk,'cancelled']))

        self.program.refresh_from_db()
        self.item.refresh_from_db()
        self.assertEqual(self.program.sessions_completed,0)
        self.assertEqual(self.program.status,'planned')
        self.assertEqual(self.item.doctor_snapshot['treatment_sessions_completed'],0)
        self.assertEqual(self.item.doctor_snapshot['treatment_sessions_remaining'],2)

    def test_patient_360_shows_real_session_progress(self):
        booking=self._booking(60)
        self.client.post(reverse('device_booking_status',args=[booking.pk,'completed']))
        response=self.client.get(reverse('patient_360',args=[self.patient.pk]))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'جلسه 1 از 2 انجام شده')
        self.assertContains(response,'1 جلسه باقی‌مانده')
