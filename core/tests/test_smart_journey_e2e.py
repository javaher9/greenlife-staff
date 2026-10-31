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
from core.jalali import format_jalali

from core.models import (
    BodyAnalysisRecord, Branch, CallCenterLeadGroup, EmployeeProfile,
    ConsultationPlan, FinancialTransaction, PatientCareNote, PatientDeviceProgram, PatientDietProgram,
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
        self.doctor = self._staff('smart-test-doctor', 'doctor', self.branch)
        self.consultant = self._staff('smart-test-consultant', 'consultant', self.branch)

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
                'conditions': ['دیابت'],  # Synthetic positive history to verify physician visibility.
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

            # 9. Physician views the very same scan + completed intake, then
            # prescribes synthetic diet, device sessions and clinical notes.
            self.client.force_login(self.doctor)
            physician = self.client.get(reverse('doctor_dashboard'), {
                'appointment': str(appt.pk),
            })
            self.assertEqual(physician.status_code, 200)
            self.assertEqual(physician.context['selected_appointment'].pk, appt.pk)
            self.assertEqual(physician.context['analysis_count'], 1)
            self.assertContains(physician, self.NAME)
            # The compact physician summary contains medical/safety history,
            # not visit reasons. Verify the submitted positive history and
            # completed screening survive the handoff to this appointment.
            summary = physician.context['medical_intake_summary']
            self.assertFalse(summary['screening_incomplete'])
            self.assertEqual(summary['sections']['بیماری‌ها'], ['دیابت'])
            self.assertContains(physician, 'دیابت')

            diet = self.client.post(reverse('doctor_action_api'), {
                'action': 'diet', 'appointment_id': str(appt.pk),
                'diet_name': 'رژیم آزمایشی استاندارد (تست هوشمند)',
                'recommendation_pack': 'توصیه نمونه؛ فقط تست',
                'print_template': 'نسخه تست',
                'note': '[TEST] بدون تجویز بالینی واقعی',
            })
            self.assertEqual(diet.status_code, 200, diet.content[:1000])
            self.assertTrue(diet.json()['ok'])
            device = self.client.post(reverse('doctor_action_api'), {
                'action': 'device', 'appointment_id': str(appt.pk),
                'device_name': 'CoolTech Define', 'area': 'شکم و پهلو',
                'sessions': '3', 'note': '[TEST] فقط نمایش گردش کار',
            })
            self.assertEqual(device.status_code, 200, device.content[:1000])
            self.assertTrue(device.json()['ok'])
            doctor_note = self.client.post(reverse('doctor_action_api'), {
                'action': 'clinical_note', 'appointment_id': str(appt.pk),
                'body': '[TEST] اندازه‌های آزمایشی اسکن بررسی شدند؛ پرونده غیرواقعی.',
            })
            self.assertEqual(doctor_note.status_code, 200, doctor_note.content[:1000])
            self.assertTrue(doctor_note.json()['ok'])
            self.assertTrue(PatientDietProgram.objects.filter(
                patient=patient, appointment=appt, prescribed_by=self.doctor,
            ).exists())
            device_program = PatientDeviceProgram.objects.get(
                patient=patient, appointment=appt, prescribed_by=self.doctor,
            )
            self.assertEqual(device_program.sessions_prescribed, 3)
            self.assertTrue(PatientCareNote.objects.filter(
                appointment=appt, author=self.doctor,
            ).exists())

            # 10. Actual physician REST handoff → consultant's own branch queue.
            handoff = self.client.post(reverse('doctor_action_api'), {
                'action': 'send_to_consultant',
                'appointment_id': str(appt.pk),
            })
            self.assertEqual(handoff.status_code, 200, handoff.content[:1000])
            self.assertTrue(handoff.json()['ok'])
            appt.refresh_from_db()
            self.assertEqual(appt.care_stage, 'consultant')
            self.assertEqual(appt.doctor_completed_by, self.doctor)
            self.assertTrue(StaffNotification.objects.filter(
                user=self.consultant, notification_type='doctor_handoff',
            ).exists())

            # 11. Consultant sees both doctor recommendations and edits one
            # fictitious line price, then finalizes the plan (no payment).
            self.client.force_login(self.consultant)
            consultant_url = reverse('consultant_sales_outcomes')
            consultant_page = self.client.get(consultant_url, {
                'appointment': str(appt.pk),
            })
            self.assertEqual(consultant_page.status_code, 200)
            self.assertContains(consultant_page, self.NAME)
            self.assertContains(consultant_page, 'CoolTech Define')
            self.assertContains(consultant_page, 'رژیم آزمایشی')
            plan = ConsultationPlan.objects.get(appointment=appt)
            self.assertEqual(plan.items.filter(source='doctor').count(), 2)
            device_line = plan.items.get(kind='device', source='doctor')
            updated = self.client.post(consultant_url, {
                'appointment_id': str(appt.pk),
                'action': 'update_item',
                'item_id': str(device_line.pk),
                'title': device_line.title,
                'area': 'شکم و پهلو',
                'quantity': '3',
                'unit_price_million': '1.5',
                'units_per_session': '1',
                'included': '1',
                'item_note': '[TEST] تعرفه نمونه؛ هیچ مطالبه واقعی نیست',
            })
            self.assertEqual(updated.status_code, 302)
            device_line.refresh_from_db()
            self.assertEqual(device_line.quantity, 3)
            self.assertEqual(int(device_line.unit_price_toman), 1500000)
            finalized = self.client.post(consultant_url, {
                'appointment_id': str(appt.pk),
                'action': 'finalize',
                'discount_million': '0',
                'plan_note': '[TEST] پکیج ساختگی برای آزمون فرآیند',
            })
            self.assertEqual(finalized.status_code, 302)
            plan.refresh_from_db()
            self.assertEqual(plan.status, 'finalized')
            self.assertEqual(plan.consultant, self.consultant)
            self.assertGreater(plan.final_amount_toman, 0)

            # 12. Send to receptionist for payment. Do not create any
            # FinancialTransaction or transfer money.
            sent_to_reception = self.client.post(consultant_url, {
                'appointment_id': str(appt.pk),
                'action': 'send_to_reception',
            })
            self.assertEqual(sent_to_reception.status_code, 302)
            plan.refresh_from_db()
            appt.refresh_from_db()
            self.assertEqual(plan.status, 'payment_pending')
            self.assertEqual(appt.care_stage, 'payment')
            self.assertIsNotNone(plan.sent_to_reception_at)
            self.assertTrue(StaffNotification.objects.filter(
                user=self.receptionist, notification_type='consultant_payment',
            ).exists())
            self.assertFalse(StaffNotification.objects.filter(
                user=self.other_receptionist, notification_type='consultant_payment',
            ).exists())

            # 13. Receptionist creates a real NEXT appointment for the same
            # synthetic patient using the actual receptionist booking POST.
            # The old visit stays untouched in payment stage.
            next_day = day + timedelta(days=7)
            if next_day.weekday() == 4:
                next_day += timedelta(days=1)
            self.client.force_login(self.receptionist)
            payment_desk = self.client.get(reverse('dashboard'))
            self.assertEqual(payment_desk.status_code, 200)
            self.assertIn(appt.pk, [
                item.pk for item in payment_desk.context['receptionist_payment_queue']
            ])
            self.assertContains(payment_desk, 'CoolTech Define')
            followup = self.client.post(reverse('receptionist_appointment_create'), {
                'full_name': self.NAME,
                'phone': self.PHONE,
                'service': 'پیگیری اسکن و مشاوره (آزمایشی)',
                'appointment_date': format_jalali(next_day),
                'appointment_time': '14:15',
                'notes': '[TEST] مراجعه مجدد؛ هیچ بیمار واقعی',
            })
            self.assertEqual(followup.status_code, 302, followup.content[:1000])
            next_visit = VisitAppointment.objects.exclude(pk=appt.pk).get(
                full_name=self.NAME, phone=self.PHONE,
            )
            self.assertEqual(next_visit.appointment_date, next_day)
            self.assertEqual(next_visit.branch, self.branch)
            self.assertEqual(next_visit.source, 'receptionist')
            self.assertEqual(next_visit.status, 'booked')
            self.assertEqual(appt.care_stage, 'payment')
            # Follow-up must resolve to the existing longitudinal profile.
            followup_profile = self.client.get(
                reverse('patient_360_from_appointment', args=[next_visit.pk])
            )
            self.assertRedirects(
                followup_profile, reverse('patient_360', args=[patient.pk]),
                fetch_redirect_response=False,
            )
            self.assertEqual(PatientProfile.objects.filter(phone=self.PHONE).count(), 1)
            self.assertEqual(BodyAnalysisRecord.objects.filter(patient=patient).count(), 1)
            self.assertFalse(FinancialTransaction.objects.exists())

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
