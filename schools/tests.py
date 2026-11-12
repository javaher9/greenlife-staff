from datetime import timedelta
from importlib import import_module
from unittest.mock import patch
from django.apps import apps
from django.contrib.auth.models import User
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import Branch, CustomerPortalMember, AuditLog
from .models import Organization, SchoolProgram, FamilyEnrollment, Child, GrowthRecord


class SchoolProgramTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='نیاوران')
        self.other_branch = Branch.objects.create(name='پونک')
        self.owner = User.objects.create_superuser('school-owner', 'owner@example.test', 'test')
        self.moradi = self.staff('school-moradi', self.branch, 'consultant', True)
        self.other = self.staff('school-other', self.other_branch, 'consultant', True)
        self.ordinary = self.staff('school-ordinary', self.branch, 'consultant', False)
        self.doctor = self.staff('school-doctor', self.branch, 'doctor', False)
        self.org = Organization.objects.create(name='مدرسه تست', branch=self.branch, created_by=self.moradi)
        self.program = SchoolProgram.objects.create(organization=self.org, coordinator=self.moradi, terms='ارزیابی و تفسیر پزشک؛ هزینه مشخص', state='open', capacity=1)
        self.member = CustomerPortalMember.objects.create(phone='09123456789', referral_code='SC-TEST')

    def staff(self, username, branch, role, allowed):
        user = User.objects.create_user(username=username, password='test')
        p = user.profile
        p.branch = branch
        p.role = role
        p.can_manage_schools = allowed
        p.save()
        return user

    def customer(self, member=None):
        self.client.logout()
        s = self.client.session
        s['gl_customer_member_id'] = (member or self.member).pk
        s['gl_customer_auth_at'] = timezone.now().timestamp()
        s.save()

    def enrollment(self, member=None, status='pending'):
        e = FamilyEnrollment.objects.create(program=self.program, member=member or self.member, parent_name='والد نمونه', consent_at=timezone.now(), terms_snapshot=self.program.terms, status=status)
        Child.objects.create(enrollment=e, name='فرزند نمونه', birth_date=timezone.localdate().replace(year=timezone.localdate().year-10), sex='f')
        return e

    def test_access_and_branch_isolation_for_every_staff_endpoint(self):
        e = self.enrollment()
        endpoints = [reverse('schools_dashboard'), reverse('schools_new'), reverse('schools_detail', args=[self.program.pk]), reverse('schools_edit', args=[self.program.pk]), reverse('schools_card', args=[self.program.pk]), reverse('schools_qr', args=[self.program.pk]), reverse('schools_coordinate', args=[e.pk])]
        for url in endpoints:
            self.assertEqual(self.client.get(url).status_code, 302)
        self.client.force_login(self.ordinary)
        for url in endpoints:
            self.assertEqual(self.client.get(url).status_code, 403)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(reverse('schools_dashboard')), self.org.name)
        for url in endpoints[2:]:
            self.assertEqual(self.client.get(url).status_code, 404)
        self.client.force_login(self.moradi)
        for url in endpoints:
            self.assertEqual(self.client.get(url).status_code, 200)
        self.moradi.profile.is_active = False
        self.moradi.profile.save()
        self.assertEqual(self.client.get(endpoints[0]).status_code, 403)

    def test_create_school_without_owner_approval_and_reject_other_branch(self):
        self.client.force_login(self.moradi)
        data = {'school_name': 'مدرسه جدید', 'branch': self.branch.pk, 'title': 'دوره اول', 'capacity': 50, 'state': 'open', 'terms': 'شرایط روشن'}
        response = self.client.post(reverse('schools_new'), data)
        self.assertEqual(response.status_code, 302)
        p = SchoolProgram.objects.get(organization__name='مدرسه جدید')
        self.assertEqual(p.state, 'open')
        self.assertEqual(p.coordinator, self.moradi)
        data['branch'] = self.other_branch.pk
        self.assertEqual(self.client.post(reverse('schools_new'), data).status_code, 200)
        self.assertEqual(SchoolProgram.objects.count(), 2)

    def test_verified_registration_consent_and_idempotence(self):
        url = reverse('schools_join', args=[self.program.token]) + '?register=1'
        self.assertIn('/customer/login/', self.client.get(url).url)
        self.customer()
        data = {'parent_name': 'مادر نمونه', 'name': 'کودک نمونه', 'birth_date': '2016-01-01', 'sex': 'f'}
        self.assertEqual(self.client.post(url, data).status_code, 200)
        self.assertEqual(FamilyEnrollment.objects.count(), 0)
        data['consent'] = 'on'
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(self.client.post(url, data).status_code, 302)
        self.assertEqual(FamilyEnrollment.objects.count(), 1)
        e = FamilyEnrollment.objects.get()
        self.assertFalse(e.adult_opt_in)
        self.assertEqual(e.terms_snapshot, self.program.terms)
        self.assertEqual(e.children.count(), 1)

    def test_activation_capacity_waitlist_and_no_duplicate_reservation(self):
        first = self.enrollment()
        self.customer()
        url = reverse('schools_family')
        self.assertEqual(self.client.post(url, {'enrollment': first.pk, 'action': 'activate'}).status_code, 400)
        self.client.post(url, {'enrollment': first.pk, 'action': 'activate', 'standalone': '1'})
        self.client.post(url, {'enrollment': first.pk, 'action': 'activate', 'standalone': '1'})
        first.refresh_from_db()
        self.assertEqual(first.status, 'ready')
        self.assertIsNotNone(first.app_activated_at)
        second_member = CustomerPortalMember.objects.create(phone='09123456780', referral_code='SC-OTHER')
        second = self.enrollment(second_member)
        self.customer(second_member)
        self.client.post(url, {'enrollment': second.pk, 'action': 'activate', 'standalone': '1'})
        second.refresh_from_db()
        self.assertEqual(second.status, 'waiting')
        self.assertEqual(self.client.post(url, {'enrollment': first.pk, 'action': 'cancel'}).status_code, 404)
        self.assertEqual(self.client.post(url, {'enrollment': 'bad', 'action': 'cancel'}).status_code, 400)
        self.customer()
        self.client.post(url, {'enrollment': first.pk, 'action': 'cancel'})
        self.customer(second_member)
        self.client.post(url, {'enrollment': second.pk, 'action': 'activate', 'standalone': '1'})
        second.refresh_from_db()
        self.assertEqual(second.status, 'ready')

    def test_closed_program_and_expired_dates_reject_new_families(self):
        self.program.ends_on = timezone.localdate() - timedelta(days=1)
        self.program.save()
        self.customer()
        url = reverse('schools_join', args=[self.program.token])
        self.assertContains(self.client.get(url), 'فعال نیست')
        self.assertEqual(self.client.get(url + '?register=1').status_code, 409)

    def test_medical_data_private_to_own_parent_and_clinicians(self):
        e = self.enrollment()
        child = e.children.get()
        secret = 'گزارش محرمانه کودک'
        self.client.force_login(self.doctor)
        url = reverse('schools_clinical_child', args=[child.pk])
        r = self.client.post(url, {'measured_on': timezone.localdate(), 'height_cm': '130', 'weight_kg': '30', 'interpretation': secret})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(GrowthRecord.objects.count(), 1)
        self.assertNotIn(secret, str(list(AuditLog.objects.values_list('metadata', flat=True))))
        self.client.force_login(self.moradi)
        self.assertEqual(self.client.get(url).status_code, 403)
        self.assertNotContains(self.client.get(reverse('schools_detail', args=[self.program.pk])), secret)
        self.customer()
        self.assertContains(self.client.get(reverse('schools_family')), secret)
        other = CustomerPortalMember.objects.create(phone='09123456781', referral_code='OTHER-PARENT')
        self.customer(other)
        self.assertNotContains(self.client.get(reverse('schools_family')), secret)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(url).status_code, 403)

    def test_booking_requires_activation_time_and_adult_permission(self):
        e = self.enrollment()
        self.client.force_login(self.moradi)
        url = reverse('schools_coordinate', args=[e.pk])
        payload = {'status': 'booked', 'adult_outcome': 'treatment'}
        self.assertEqual(self.client.post(url, payload).status_code, 200)
        e.refresh_from_db()
        self.assertEqual(e.status, 'pending')
        e.app_activated_at = timezone.now()
        e.save()
        payload.update(appointment_at=(timezone.localtime() + timedelta(days=3)).replace(hour=10, minute=0, second=0, microsecond=0).isoformat(), adult_outcome='none')
        self.assertEqual(self.client.post(url, payload).status_code, 302)
        e.refresh_from_db()
        self.assertEqual(e.status, 'booked')
        self.assertIsNotNone(e.visit_appointment_id)
        self.assertEqual(e.visit_appointment.full_name, e.parent_name)

    def test_csrf_required_and_no_patient_data_in_pwa_or_qr(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.moradi)
        before = SchoolProgram.objects.count()
        response = client.post(reverse('schools_new'), {})
        self.assertEqual(response.status_code, 302)  # Existing CSRF recovery redirects without writing.
        self.assertEqual(response.url, reverse('schools_new'))
        self.assertEqual(SchoolProgram.objects.count(), before)
        self.assertEqual(self.client.get(reverse('schools_manifest')).status_code, 200)
        self.assertNotContains(self.client.get(reverse('schools_service_worker')), 'caches.open')
        self.client.force_login(self.moradi)
        response = self.client.get(reverse('schools_qr', args=[self.program.pk]))
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertTrue(response.content.startswith(b'\x89PNG'))
        self.assertNotContains(self.client.get(reverse('schools_card', args=[self.program.pk])), self.member.phone)

    def test_coordinator_grant_requires_unique_active_niavaran_moradi(self):
        grant = import_module('core.migrations.0121_grant_school_coordinator').grant_coordinator
        self.moradi.last_name = 'مرادی'
        self.moradi.save()
        self.moradi.profile.can_manage_schools = False
        self.moradi.profile.save()
        grant(apps, None)
        self.moradi.profile.refresh_from_db()
        self.assertTrue(self.moradi.profile.can_manage_schools)
        self.moradi.profile.can_manage_schools = False
        self.moradi.profile.save()
        duplicate = self.staff('school-duplicate', self.branch, 'consultant', False)
        duplicate.last_name = 'مرادی'
        duplicate.save()
        grant(apps, None)
        self.moradi.profile.refresh_from_db()
        duplicate.profile.refresh_from_db()
        self.assertFalse(self.moradi.profile.can_manage_schools)
        self.assertFalse(duplicate.profile.can_manage_schools)

    @override_settings(PUBLIC_BASE_URL='https://app.greenlifeclinics.com')
    def test_invitation_uses_public_host_even_from_lan(self):
        self.client.force_login(self.moradi)
        response = self.client.get(reverse('schools_detail', args=[self.program.pk]), HTTP_HOST='192.168.40.96')
        self.assertContains(response, 'https://app.greenlifeclinics.com/customer/schools/')
        self.assertNotContains(response, 'http://192.168.40.96/customer/schools/')

    def test_reception_changes_synchronize_family_after_commit(self):
        from core.models import VisitAppointment
        e = self.enrollment()
        appointment = VisitAppointment.objects.create(branch=self.branch, full_name=e.parent_name, phone=self.member.phone, service='مدارس', appointment_date=timezone.localdate(), appointment_time='10:00', created_by=self.moradi)
        e.visit_appointment = appointment
        e.save()
        with self.captureOnCommitCallbacks(execute=True):
            appointment.status = 'arrived'
            appointment.save()
        e.refresh_from_db()
        self.assertEqual(e.status, 'attended')
        self.assertIsNotNone(e.appointment_at)
