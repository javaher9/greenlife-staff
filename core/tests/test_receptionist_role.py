from datetime import time
from core.tests.test_dual_credentials import DualCredentialTests as DualCredentialRegressionTests
from django.contrib.auth.models import User
from django.test import TestCase
from django.utils import timezone
from django.urls import reverse

from core.models import Branch, EmployeeProfile, ReferralLead, ReferralProfile, Task, VisitAppointment


class ReceptionistRoleTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='نیاوران')
        self.user=User.objects.create_user(
            username='reception-test',
            password='test-password',
            first_name='منشی',
            last_name='آزمایشی',
        )
        EmployeeProfile.objects.update_or_create(
            user=self.user,
            defaults={
                'role':'receptionist',
                'branch':self.branch,
                'job_title':'منشی',
                'is_active':True,
            },
        )
        self.user=User.objects.get(pk=self.user.pk)
        self.client.force_login(self.user)

    def test_role_has_distinct_persian_label(self):
        self.assertIn(('receptionist','منشی'),EmployeeProfile.ROLE_CHOICES)
        self.assertEqual(self.user.profile.get_role_display(),'منشی')

    def test_desktop_dashboard_is_isolated_white_receptionist_workspace(self):
        Task.objects.create(
            title='پیگیری مراجعه‌کننده',
            assigned_to=self.user,
            created_by=self.user,
        )
        response=self.client.get(reverse('dashboard'),HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,'core/receptionist_dashboard.html')
        self.assertContains(response,'پنل منشی')
        self.assertContains(response,'پیگیری مراجعه‌کننده')
        self.assertContains(response,'تم سفید')
        self.assertNotContains(response,'GreenLife')
        self.assertNotContains(response,'مشتری اول')

    def test_desktop_dashboard_exposes_live_reception_actions(self):
        VisitAppointment.objects.create(
            branch=self.branch,
            full_name='بیمار تست',
            phone='09120000000',
            service='مشاوره',
            appointment_date=timezone.localdate(),
            appointment_time=time(10,0),
            status='booked',
            care_stage='doctor',
            source='call_center',
        )
        response=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        )
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'میز عملیات پذیرش')
        self.assertContains(response,'منتظر پزشک')
        self.assertContains(response,'✓ پذیرش')
        self.assertContains(response,'پرونده ۳۶۰')
        self.assertContains(response,'بیمار انتخاب‌شده')
        self.assertContains(response,'data-wait-chip')
        self.assertContains(response,'بیمار تست')

    def test_receptionist_checkin_can_return_to_dashboard(self):
        appointment=VisitAppointment.objects.create(
            branch=self.branch,
            full_name='مراجعه سریع',
            phone='09123334444',
            service='مشاوره',
            appointment_date=timezone.localdate(),
            appointment_time=time(11,0),
            status='booked',
            care_stage='doctor',
            source='call_center',
        )
        response=self.client.post(
            reverse('receptionist_appointment_status',args=[appointment.pk,'arrived']),
            {'next':'dashboard'},
            HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
        )
        self.assertRedirects(response,reverse('dashboard'))
        appointment.refresh_from_db()
        self.assertEqual(appointment.status,'arrived')

    def test_no_show_returns_lead_to_call_center_follow_up(self):
        operator=User.objects.create_user(
            username='no-show-operator',password='pass',first_name='اپراتور',
        )
        operator_profile=operator.profile
        operator_profile.role='call_center'
        operator_profile.branch=self.branch
        operator_profile.save(update_fields=['role','branch'])

        ref_user=User.objects.create_user(username='no-show-ref',password='pass')
        referrer=ReferralProfile.objects.create(
            user=ref_user,referral_code='NOSHOW-REF',
        )
        lead=ReferralLead.objects.create(
            referrer=referrer,
            full_name='بیمار عدم مراجعه',
            phone='09124445566',
            status='appointment',
            assigned_to=operator_profile,
            first_appointment_by=operator,
        )
        appointment=VisitAppointment.objects.create(
            lead=lead,
            branch=self.branch,
            full_name=lead.full_name,
            phone=lead.phone,
            service='مشاوره',
            appointment_date=timezone.localdate(),
            appointment_time=time(12,0),
            status='booked',
            care_stage='doctor',
            source='call_center',
            created_by=operator,
        )

        response=self.client.post(
            reverse('receptionist_appointment_status',args=[appointment.pk,'no_show']),
            {'next':'dashboard'},
        )
        self.assertRedirects(response,reverse('dashboard'))
        appointment.refresh_from_db()
        lead.refresh_from_db()
        self.assertEqual(appointment.status,'no_show')
        self.assertEqual(lead.status,'contacted')
        self.assertEqual(lead.contact_result,'follow_up')
        self.assertEqual(lead.next_follow_up,timezone.localdate()+timezone.timedelta(days=1))
        self.assertTrue(
            Task.objects.filter(
                assigned_to=operator,
                title__startswith='پیگیری عدم مراجعه',
            ).exists()
        )

    def test_phone_dashboard_keeps_existing_dark_personnel_experience(self):
        response=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 16; Pixel 9) AppleWebKit/537.36 Chrome/140 Mobile Safari/537.36',
            HTTP_SEC_CH_UA_MOBILE='?1',
        )
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,'core/dashboard.html')
        self.assertContains(response,'gl-employee-dashboard')
        self.assertContains(response,'حضور و غیاب')
        self.assertContains(response,'gl-premium-dark')
        self.assertNotContains(response,'نسخه دسکتاپ منشی')

    def test_android_tablet_without_mobile_hint_uses_desktop_workspace(self):
        response=self.client.get(
            reverse('dashboard'),
            HTTP_USER_AGENT='Mozilla/5.0 (Linux; Android 16; Tablet) AppleWebKit/537.36 Chrome/140 Safari/537.36',
        )
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,'core/receptionist_dashboard.html')

    def test_regular_employee_dashboard_is_unchanged(self):
        employee=User.objects.create_user(username='regular-staff',password='pass',first_name='کارمند')
        EmployeeProfile.objects.update_or_create(
            user=employee,
            defaults={'role':'employee','branch':self.branch,'is_active':True},
        )
        self.client.force_login(employee)
        response=self.client.get(reverse('dashboard'),HTTP_USER_AGENT='Mozilla/5.0 (Windows NT 10.0; Win64; x64)')
        self.assertEqual(response.status_code,200)
        self.assertTemplateUsed(response,'core/dashboard.html')
        self.assertContains(response,'gl-employee-dashboard')
        self.assertNotContains(response,'نسخه دسکتاپ منشی')
