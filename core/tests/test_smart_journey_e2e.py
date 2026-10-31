"""Full no-outbound CRM journey through real Django HTTP views.

Every fixture and record is in Django's disposable test database.
No live appointments, finance, patient records, or SMS are ever created.
"""
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    BodyAnalysisRecord, Branch, CallCenterLeadGroup, EmployeeProfile,
    PatientProfile, ReferralLead, StaffNotification, VisitAppointment,
)
from intake.models import IntakeInvitation


class SmartPatientJourneyE2ETest(TestCase):
    NAME = 'تست هوشمند'
    # A placeholder used strictly in the rollback-only test database.
    PHONE = '09120000000'
    TOKEN = 'smart-test-intake-token-not-for-real-sms-2026'

    def setUp(self):
        self.branch = Branch.objects.create(name='نیاوران')
        self.call_branch = Branch.objects.create(name='کال‌سنتر')
        self.other_branch = Branch.objects.create(name='پونک')
        self.group = CallCenterLeadGroup.objects.create(name='گروه آزمایشی گردش کار')
        self.call_user = self._staff('smart-test-operator', 'call_center', self.call_branch)
        self.receptionist = self._staff('smart-test-reception', 'receptionist', self.branch)
        self.other_receptionist = self._staff('smart-test-poo', 'receptionist', self.other_branch)

    def _staff(self, username, role, branch):
        user = User.objects.create_user(username=username, password='test-only-password')
        EmployeeProfile.objects.update_or_create(
            user=user, defaults={'role': role, 'branch': branch, 'is_active': True}
        )
        user.refresh_from_db()
        return user

    def test_smart_lead_to_branch_reception_intake_and_scan(self):
        # Use a non-Friday simulated service day, so production time/Friday
        # restriction cannot cause flaky tests. The database is temporary.
        day = timezone.localdate()
        if day.weekday() == 4:
            day += timedelta(days=1)

        with patch('django.utils.timezone.localdate', return_value=day), \
             patch('core.appointment_views._queue_appointment_messages') as queued_sms, \
             patch('intake.views.send_sms') as intake_sms, \
             patch('intake.views.secrets.token_urlsafe', return_value=self.TOKEN):
            # 1. The actual call-center direct-lead POST.
            self.client.force_login(self.call_user)
            created = self.client.post(reverse('call_center_direct_lead_create'), {
                'full_name': self.NAME,
                'phone': self.PHONE,
                'group': str(self.group.pk),
                'interested_service': 'اسکن و آنالیز آزمایشی',
                'notes': '[TEST] فقط آزمایش یکپارچگی؛ بدون فرد واقعی یا رضایت پیامکی',
            })
            self.assertEqual(created.status_code, 302, created.content[:600])
            lead = ReferralLead.objects.get(full_name=self.NAME, phone=self.PHONE)
            self.assertEqual(lead.assigned_to_id, self.call_user.profile.pk)
            self.assertEqual(lead.group_id, self.group.pk)
            self.assertIn('[entry:direct]', lead.notes)
            lead_page = self.client.get(reverse('call_center_lead', args=[lead.pk]))
            self.assertEqual(lead_page.status_code, 200)

            # 2. Book the same lead via real seven-day calendar slot API.
            booked = self.client.post(
                reverse('call_center_appointment_slot_create', args=[lead.pk]), {
                    'branch': str(self.branch.pk),
                    'appointment_date': day.isoformat(),
                    'appointment_time': '09:15',
                    'notes': '[TEST] تست هوشمند؛ نوبت آزمایشی',
                }
            )
            self.assertEqual(booked.status_code, 200, booked.content[:1000])
            self.assertTrue(booked.json()['ok'])
            appt = VisitAppointment.objects.get(lead=lead)
            self.assertEqual(appt.full_name, self.NAME)
            self.assertEqual(appt.branch_id, self.branch.pk)
            self.assertEqual(appt.status, 'booked')
            lead.refresh_from_db()
            self.assertEqual(lead.status, 'appointment')
            self.assertTrue(StaffNotification.objects.filter(
                user=self.receptionist, notification_type='appointment',
            ).exists())
            self.assertFalse(StaffNotification.objects.filter(
                user=self.other_receptionist, notification_type='appointment',
            ).exists())

            # 3. It must appear in the intended receptionist's live panel.
            self.client.force_login(self.receptionist)
            desk = self.client.get(
                reverse('dashboard'),
                HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            )
            self.assertEqual(desk.status_code, 200)
            self.assertContains(desk, self.NAME)
            self.assertNotContains(
                self._other_branch_dashboard(), self.NAME,
            )

            # 4. Receptionist performs actual check-in, then opens patient 360.
            arrived = self.client.post(
                reverse('receptionist_appointment_status', args=[appt.pk, 'arrived']),
                {'next': 'dashboard'},
            )
            self.assertEqual(arrived.status_code, 302)
            appt.refresh_from_db()
            self.assertEqual(appt.status, 'arrived')
            lead.refresh_from_db()
            self.assertEqual(lead.status, 'visited')
            patient_link = self.client.get(
                reverse('patient_360_from_appointment', args=[appt.pk])
            )
            self.assertEqual(patient_link.status_code, 302)
            patient = PatientProfile.objects.get(phone=self.PHONE)
            self.assertEqual(patient.full_name, self.NAME)
            self.assertEqual(patient.home_branch, self.branch)

            # 5. Send patient intake invitation via the real receptionist route,
            # but intercept its SMS gateway; no network messaging is possible.
            invite_sent = self.client.post(
                reverse('intake_send_link', args=[appt.pk])
            )
            self.assertEqual(invite_sent.status_code, 302)
            intake_sms.assert_called_once()
            invitation = IntakeInvitation.objects.get(appointment=appt)
            self.assertEqual(invitation.sms_status, 'accepted')

            # 6. Simulate patient browser (no staff login), fill + submit all
            # required fields; validate reception completion notification.
            patient_browser = Client()
            public_url = reverse('intake_public_form', args=[self.TOKEN])
            opened = patient_browser.get(public_url)
            self.assertEqual(opened.status_code, 200)
            submitted = patient_browser.post(public_url, {
                'reasons': ['کاهش وزن'],
                'conditions': [],
                'safety_flags': [],
                'medications': 'ندارد (فرضی)',
                'allergies': 'ندارد (فرضی)',
                'comments': 'دادهٔ نمونه تست هوشمند؛ هیچ شخص واقعی وجود ندارد.',
                'screening_confirmed': 'on',
                'consent': 'on',
            })
            self.assertEqual(submitted.status_code, 200)
            invitation.refresh_from_db()
            self.assertIsNotNone(invitation.completed_at)
            self.assertEqual(invitation.answers['reasons'], ['کاهش وزن'])
            self.assertTrue(invitation.answers['required_screening_complete'])
            self.assertTrue(StaffNotification.objects.filter(
                user=self.receptionist,
                title='فرم اطلاعات اولیه تکمیل شد',
            ).exists())

            # 7. On the same service day, the receptionist scans and records six
            # imaginary figures via the actual scan-station POST form.
            scan_list = self.client.get(reverse('scan_station'))
            self.assertEqual(scan_list.status_code, 200)
            self.assertContains(scan_list, self.NAME)
            scan = self.client.post(reverse('scan_station'), {
                'appointment_id': str(appt.pk),
                'operator_id': str(self.receptionist.profile.pk),
                'weight_kg': '72.50',
                'inbody_score': '78.0',
                'skeletal_muscle_kg': '29.50',
                'fat_kg': '21.00',
                'whr': '0.84',
                'visceral_fat': '8.0',
            })
            self.assertEqual(scan.status_code, 302, scan.content[:600])
            body_record = BodyAnalysisRecord.objects.get(
                patient=patient,
                measurements__scan_appointment_id=appt.pk,
            )
            self.assertEqual(str(body_record.weight_kg), '72.50')
            self.assertEqual(body_record.measurements['fat_kg'], '21.00')
            self.assertEqual(body_record.measurements['whr'], '0.84')
            scanned_list = self.client.get(reverse('scan_station'))
            self.assertTrue(next(
                a.scan_completed for a in scanned_list.context['queue']
                if a.pk == appt.pk
            ))

            # 8. Scan cannot be registered twice for one appointment.
            duplicate = self.client.post(reverse('scan_station'), {
                'appointment_id': str(appt.pk),
                'operator_id': str(self.receptionist.profile.pk),
                'weight_kg': '72.50', 'inbody_score': '78.0',
                'skeletal_muscle_kg': '29.50', 'fat_kg': '21.00',
                'whr': '0.84', 'visceral_fat': '8.0',
            })
            self.assertEqual(duplicate.status_code, 302)
            self.assertEqual(BodyAnalysisRecord.objects.filter(
                measurements__scan_appointment_id=appt.pk,
            ).count(), 1)
            self.assertEqual(VisitAppointment.objects.filter(lead=lead).count(), 1)
            # All output messages are mocked, not sent. Appointment messages
            # registered through on_commit never touch a live provider in a test.
            queued_sms.assert_not_called()

    def _other_branch_dashboard(self):
        self.client.force_login(self.other_receptionist)
        try:
            return self.client.get(
                reverse('dashboard'),
                HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            )
        finally:
            self.client.force_login(self.receptionist)
