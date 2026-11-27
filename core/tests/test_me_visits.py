from datetime import timedelta, time
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from core.models import (
    Branch, CustomerPortalMember, CustomerServiceRequest, PatientDeviceProgram,
    PatientLipolyticProgram, PatientProfile, VisitAppointment,
)


class MeVisitTrackingTests(TestCase):
    def setUp(self):
        self.url = '/customer/me/visits/'
        self.branch = Branch.objects.create(name='Tracking branch')
        self.member = CustomerPortalMember.objects.create(phone='09120003001', referral_code='track1')
        other = CustomerPortalMember.objects.create(phone='09120003002', referral_code='track2')
        CustomerServiceRequest.objects.create(member=other, kind='visit', branch=self.branch)
        self.row = CustomerServiceRequest.objects.create(member=self.member, kind='visit', branch=self.branch,
            preferred_date=timezone.localdate()+timedelta(days=1), staff_note='private internal closure',
            next_followup_at=timezone.now()+timedelta(hours=1))
        session = self.client.session
        session['gl_customer_member_id'] = self.member.pk
        session['gl_customer_auth_at'] = timezone.now().timestamp()
        session.save()

    def data(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertIn('no-store', response['Cache-Control'])
        return response.json()['requests']

    def test_owner_only_and_no_internal_fields(self):
        self.assertEqual(Client().get(self.url).status_code, 401)
        rows = self.data()
        self.assertEqual([r['id'] for r in rows], [self.row.pk])
        self.assertEqual(rows[0]['state'], 'pending')
        self.assertIsNone(rows[0]['appointment'])
        self.assertEqual(rows[0]['stage'], 1)
        for field in ('staff_note', 'next_followup_at', 'assigned_to', 'phone', 'address'):
            self.assertNotIn(field, rows[0])
        self.assertNotIn('private internal closure', str(rows))
        self.assertEqual(self.client.post(self.url).status_code, 405)

    def test_actual_booking_changes_and_cancelled_are_fresh(self):
        booking = VisitAppointment.objects.create(branch=self.branch,full_name='Test',phone=self.member.phone,
            appointment_date=timezone.localdate()+timedelta(days=3),appointment_time=time(10,30))
        self.row.status='booked'; self.row.visit_appointment=booking; self.row.save()
        data=self.data()[0]
        self.assertEqual(data['state'],'booked')
        self.assertEqual(data['appointment']['time'],'10:30')
        self.assertNotEqual(data['appointment']['date'],data['preferred_date'])
        booking.appointment_time=time(14,45); booking.save()
        self.assertEqual(self.data()[0]['appointment']['time'],'14:45')
        for status in ('cancelled','no_show','arrived','completed'):
            booking.status=status;booking.save()
            self.assertEqual(self.data()[0]['state'],status)
        booking.status='booked';booking.appointment_date=timezone.localdate()-timedelta(days=1);booking.save()
        self.assertEqual(self.data()[0]['state'],'past')

    def test_closed_missing_booking_and_empty(self):
        self.row.status='declined';self.row.save()
        self.assertEqual(self.data()[0]['state'],'declined')
        self.row.status='booked';self.row.save()
        data=self.data()[0]
        self.assertEqual(data['state'],'needs_review')
        self.assertIsNone(data['appointment'])
        self.row.delete()
        self.assertEqual(self.data(),[])

    def test_customer_appointments_from_real_requests_and_visible_booking(self):
        url = reverse('customer_appointments')
        self.assertIn('next=%2Fcustomer%2Fappointments%2F', Client().get(url).url)
        response = self.client.get(url)
        self.assertContains(response, 'ویزیت‌های من')
        self.assertContains(response, 'در انتظار بررسی')
        self.assertNotContains(response, 'private internal closure')
        self.assertContains(response, f'href="{reverse("customer_request", args=["visit"])}"')
        self.assertContains(response, f'href="{reverse("customer_request", args=["device"])}"')
        self.assertEqual([row['id'] for row in response.context['visit_requests']], [self.row.pk])
        self.assertIn('no-store', response['Cache-Control'])
        self.row.status = 'booked'
        self.row.visit_appointment = VisitAppointment.objects.create(
            branch=self.branch, full_name='Test', phone=self.member.phone,
            appointment_date=timezone.localdate() + timedelta(days=1), appointment_time=time(10, 30),
        )
        self.row.save()
        self.assertContains(self.client.get(url), '10:30')

    def test_program_counts_are_visible_only_for_the_verified_patient(self):
        patient = PatientProfile.objects.create(full_name='Fixture patient', phone=self.member.phone)
        other = PatientProfile.objects.create(full_name='Other patient', phone='09120003002')
        PatientDeviceProgram.objects.create(patient=patient, device_name='Fixture device', sessions_prescribed=4, sessions_completed=2)
        PatientLipolyticProgram.objects.create(patient=patient, protocol_name='Fixture lipolytic', sessions_prescribed=3, sessions_completed=1)
        PatientDeviceProgram.objects.create(patient=other, device_name='Other patient device')
        page = self.client.get(reverse('customer_appointments'))
        self.assertContains(page, 'Fixture device')
        self.assertContains(page, 'Fixture lipolytic')
        self.assertContains(page, '2 از 4 جلسه')
        self.assertNotContains(page, 'Other patient device')
