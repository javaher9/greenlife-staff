"""Safety checks for call-center booking and individual remote attendance."""
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Attendance, Branch, EmployeeProfile, ReferralLead, ReferralProfile


class RemoteCallCenterAppointmentTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(
            name='Remote test clinic',
            geofence_enabled=True,
            latitude='35.750000', longitude='51.350000',
            attendance_radius_m=150,
        )
        self.call_branch = Branch.objects.create(name='Remote Call Center')
        self.operator = User.objects.create_user(
            username='remote-cc-operator', password='test',
        )
        self.profile, _ = EmployeeProfile.objects.update_or_create(
            user=self.operator,
            defaults={
                'role':'call_center',
                'branch':self.call_branch,
                'is_active':True,
                'remote_attendance_enabled':True,
            },
        )
        self.refuser = User.objects.create_user(username='remote-referrer',password='test')
        self.referrer, _ = ReferralProfile.objects.get_or_create(
            user=self.refuser, defaults={'referral_code':'TESTREMOTEBOOKING'}
        )
        self.lead = ReferralLead.objects.create(
            referrer=self.referrer,
            full_name='بیمار نوبت دورکاری',
            phone='09120006789',
            assigned_to=self.profile,
        )
        self.client.force_login(self.operator)

    def test_operator_can_find_own_lead_and_open_simple_booking_form(self):
        calendar = self.client.get(reverse('appointment_schedule'))
        self.assertEqual(calendar.status_code,200)
        self.assertContains(calendar,'انتخاب بیمار از لیدهای من')
        self.assertContains(calendar,self.lead.full_name)
        selected = self.client.get(reverse('appointment_schedule'),{'lead':self.lead.pk})
        self.assertEqual(selected.status_code,200)
        self.assertContains(selected,'ثبت نوبت با فرم ساده')
        quick=self.client.get(
            reverse('call_center_appointment_create',args=[self.lead.pk]),
            {'simple':'1'},
        )
        self.assertEqual(quick.status_code,200)
        self.assertContains(quick,'ثبت قطعی نوبت')

    def test_someone_elses_lead_not_accessible_through_booking(self):
        other=User.objects.create_user('remote-other-operator',password='test')
        other_profile,_=EmployeeProfile.objects.update_or_create(
            user=other,
            defaults={'role':'call_center','branch':self.call_branch,'is_active':True},
        )
        self.lead.assigned_to=other_profile
        self.lead.save(update_fields=['assigned_to'])
        response=self.client.get(
            reverse('call_center_appointment_create',args=[self.lead.pk]),
            {'simple':'1'},
        )
        self.assertEqual(response.status_code,404)

    def test_explicit_remote_permission_allows_no_gps_and_breaks(self):
        self.profile.branch=self.branch
        self.profile.save(update_fields=['branch'])
        first=self.client.post(reverse('attendance'),{'action':'checkin'})
        self.assertEqual(first.status_code,302)
        attendance=Attendance.objects.get(user=self.operator,date=timezone.localdate())
        self.assertIsNotNone(attendance.check_in)
        self.assertEqual(attendance.check_in_location_status,'remote')
        self.client.post(reverse('attendance'),{'action':'break_start'})
        attendance.refresh_from_db()
        self.assertIsNotNone(attendance.break_started_at)
        self.client.post(reverse('attendance'),{'action':'break_end'})
        attendance.refresh_from_db()
        self.assertIsNone(attendance.break_started_at)
        final=self.client.post(reverse('attendance'),{'action':'checkout'})
        self.assertEqual(final.status_code,302)
        attendance.refresh_from_db()
        self.assertIsNotNone(attendance.check_out)

    def test_without_remote_permission_geofence_still_required(self):
        self.profile.branch=self.branch
        self.profile.remote_attendance_enabled=False
        self.profile.save(update_fields=['branch','remote_attendance_enabled'])
        response=self.client.post(reverse('attendance'),{'action':'checkin'})
        self.assertEqual(response.status_code,302)
        self.assertFalse(Attendance.objects.filter(user=self.operator,date=timezone.localdate()).exists())

    def test_consultant_cannot_use_call_center_remote_exemption(self):
        self.profile.branch=self.branch
        self.profile.role='consultant'
        self.profile.save(update_fields=['branch','role'])
        response=self.client.post(reverse('attendance'),{'action':'checkin'})
        self.assertEqual(response.status_code,302)
        self.assertFalse(Attendance.objects.filter(user=self.operator,date=timezone.localdate()).exists())
