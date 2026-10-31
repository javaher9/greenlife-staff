"""HTTP end-to-end smoke test: call center -> receptionist -> intake -> scan.

This intentionally uses the isolated Django test database. All people, phone
numbers and measurements are synthetic; provider SMS calls are mocked. No
patient record, appointment or SMS is written to live production.
"""
import re
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import (
    BodyAnalysisRecord, Branch, CallCenterLeadGroup, EmployeeProfile,
    FinancialTransaction, PatientProfile, ReferralLead, StaffNotification,
    VisitAppointment,
)
from intake.models import IntakeInvitation


class SmartTestWholeReceptionFlow(TestCase):
    NAME = 'تست هوشمند'
    PHONE = '09120000987'  # Synthetic and NEVER called or messaged.

    def setUp(self):
        self.niavaran = Branch.objects.create(name='نیاوران')
        self.poonak = Branch.objects.create(name='پونک')
        self.cc_branch = Branch.objects.create(name='کال‌سنتر')
        self.cc = self.make_staff('smart-cc', 'call_center', self.cc_branch)
        self.reception = self.make_staff('smart-reception', 'receptionist', self.niavaran)
        self.other_reception = self.make_staff('smart-other-reception', 'receptionist', self.poonak)
        self.group = CallCenterLeadGroup.objects.create(name='گروه تست هوشمند', is_default=False)
        self.visit_day = timezone.localdate() + timedelta(days=1)
        while self.visit_day.weekday() == 4:  # Clinic closed on Friday.
            self.visit_day += timedelta(days=1)

    def make_staff(self, username, role, branch):
        user = User.objects.create_user(username=username, password='test-password')
        EmployeeProfile.objects.update_or_create(
            user=user,
            defaults={'role': role, 'branch': branch, 'is_active': True},
        )
        return user

    def test_smart_lead_to_complete_intake_and_six_factor_scan(self):
        # 1. Enter new synthetic lead through the actual call-center HTTP form.
        self.client.force_login(self.cc)
        response = self.client.post(reverse('call_center_direct_lead_create'), {
            'full_name': self.NAME, 'phone': self.PHONE,
            'group': str(self.group.pk), 'interested_service': 'مشاوره آزمایشی',
            'notes': '[TEST_ONLY] ورودی ساختگی برای آزمون یکپارچه',
        })
        self.assertEqual(response.status_code, 302)
        lead = ReferralLead.objects.get(phone=self.PHONE)
        self.assertEqual(lead.full_name, self.NAME)
        self.assertEqual(lead.assigned_to_id, self.cc.profile.pk)
        self.assertEqual(lead.group_id, self.group.pk)

        # 2. Book in Niavaran with the normal seven-day calendar REST handler.
        # Execute transaction callbacks, but explicitly mock appointment SMS.
        with patch('core.appointment_views._queue_appointment_messages') as appointment_sms:
            with self.captureOnCommitCallbacks(execute=True):
                booked = self.client.post(
                    reverse('call_center_appointment_slot_create', args=[lead.pk]), {
                        'branch': str(self.niavaran.pk),
                        'appointment_date': self.visit_day.isoformat(),
                        'appointment_time': '10:15',
                        'notes': '[TEST_ONLY] فقط آزمون سیستم',
                    },
                )
        self.assertEqual(booked.status_code, 200, booked.content)
        self.assertTrue(booked.json()['ok'])
        appointment = VisitAppointment.objects.get(lead=lead)
        self.assertEqual(appointment.status, 'booked')
        self.assertEqual(appointment.branch_id, self.niavaran.pk)
        self.assertEqual(appointment.source, 'call_center')
        self.assertTrue(StaffNotification.objects.filter(
            user=self.reception, title='نوبت جدید ثبت شد',
        ).exists())
        self.assertFalse(StaffNotification.objects.filter(
            user=self.other_reception, title='نوبت جدید ثبت شد',
        ).exists())
        appointment_sms.assert_called_once_with(appointment.pk)
        lead.refresh_from_db()
        self.assertEqual(lead.status, 'appointment')

        # 3. The same real appointment must be accessible in the receptionist calendar.
        self.client.force_login(self.reception)
        calendar = self.client.get(
            reverse('appointment_schedule'),
            {'date': self.visit_day.isoformat()},
        )
        self.assertEqual(calendar.status_code, 200)
        self.assertContains(calendar, self.NAME)
        arrived = self.client.post(
            reverse('receptionist_appointment_status', args=[appointment.pk, 'arrived']),
            {'next': 'dashboard'},
        )
        self.assertEqual(arrived.status_code, 302)
        appointment.refresh_from_db()
        lead.refresh_from_db()
        self.assertEqual(appointment.status, 'arrived')
        self.assertEqual(lead.status, 'visited')

        # 4. Receptionist must not be able to silently create a patient consent
        # form; the URL is sent explicitly. Mock the SMS gateway and use token
        # only inside this isolated test.
        with patch('intake.views.send_sms') as fake_intake_sms:
            sent = self.client.post(reverse('intake_send_link', args=[appointment.pk]))
        self.assertEqual(sent.status_code, 302)
        fake_intake_sms.assert_called_once()
        sms_text = fake_intake_sms.call_args.args[1]
        match = re.search(r'/intake/form/([a-zA-Z0-9_-]{32,128})/', sms_text)
        self.assertIsNotNone(match, 'The receptionist SMS must contain a real intake URL.')
        token = match.group(1)
        invitation = IntakeInvitation.objects.get(appointment=appointment)
        self.assertEqual(invitation.sms_status, 'accepted')  # Mock provider acceptance.
        self.assertIsNone(invitation.completed_at)

        # 5. Synthetic patient opens and submits all required intake fields.
        self.client.logout()
        form_url = reverse('intake_public_form', args=[token])
        form_page = self.client.get(form_url)
        self.assertEqual(form_page.status_code, 200)
        self.assertContains(form_page, 'فرم اطلاعات اولیه')
        completed = self.client.post(form_url, {
            'reasons': ['کاهش وزن'],
            'conditions': [],
            'safety_flags': [],
            'medications': 'ندارد (داده ساختگی)',
            'allergies': 'ندارد (داده ساختگی)',
            'comments': '[TEST_ONLY] اطلاعات آزمایشی و بدون هویت واقعی',
            'screening_confirmed': 'on',
            'consent': 'on',
        })
        self.assertEqual(completed.status_code, 200)
        self.assertContains(completed, 'ثبت')
        invitation.refresh_from_db()
        self.assertIsNotNone(invitation.completed_at)
        self.assertEqual(invitation.answers['reasons'], ['کاهش وزن'])
        self.assertTrue(invitation.answers['required_screening_complete'])
        self.assertTrue(StaffNotification.objects.filter(
            user=self.reception, title='فرم اطلاعات اولیه تکمیل شد',
        ).exists())

        # 6. Receptionist opens patient 360 and creates a matching profile,
        # then verifies intake and scans on the booked day.
        self.client.force_login(self.reception)
        patient_redirect = self.client.get(
            reverse('patient_360_from_appointment', args=[appointment.pk]),
        )
        self.assertEqual(patient_redirect.status_code, 302)
        patient = PatientProfile.objects.get(phone=self.PHONE)
        self.assertEqual(patient.full_name, self.NAME)

        scan_payload = {
            'appointment_id': str(appointment.pk),
            'operator_id': str(self.reception.profile.pk),
            'weight_kg': '72.40', 'inbody_score': '78',
            'skeletal_muscle_kg': '27.30', 'fat_kg': '23.70',
            'whr': '0.88', 'visceral_fat': '9',
        }
        with patch('core.scan_station_views.timezone.localdate',
                   return_value=self.visit_day):
            scan_page = self.client.get(reverse('scan_station'))
            self.assertEqual(scan_page.status_code, 200)
            self.assertContains(scan_page, self.NAME)
            saved = self.client.post(reverse('scan_station'), scan_payload)
            self.assertEqual(saved.status_code, 302)
            # Accidental second click must not create a duplicate scan.
            duplicate = self.client.post(reverse('scan_station'), scan_payload)
            self.assertEqual(duplicate.status_code, 302)

        analysis = BodyAnalysisRecord.objects.get(patient=patient)
        self.assertEqual(analysis.weight_kg, Decimal('72.40'))
        self.assertEqual(analysis.inbody_score, Decimal('78'))
        self.assertEqual(analysis.skeletal_muscle_kg, Decimal('27.30'))
        self.assertEqual(analysis.visceral_fat, Decimal('9'))
        self.assertEqual(analysis.measurements['fat_kg'], '23.70')
        self.assertEqual(analysis.measurements['whr'], '0.88')
        self.assertEqual(analysis.measurements['scan_appointment_id'], appointment.pk)
        self.assertEqual(BodyAnalysisRecord.objects.filter(patient=patient).count(), 1)

        # 7. Other-branch receptionist cannot check-in or send intake for patient.
        self.client.force_login(self.other_reception)
        self.assertEqual(self.client.post(
            reverse('intake_send_link', args=[appointment.pk]),
        ).status_code, 404)
        self.assertEqual(self.client.post(
            reverse('receptionist_appointment_status', args=[appointment.pk, 'arrived']),
        ).status_code, 404)

        # No financial transaction is created during this test cycle.
        self.assertFalse(FinancialTransaction.objects.exists())
