"""GreenLife ME body page only exposes the OTP-verified patient's scans and photos."""
from datetime import time
from decimal import Decimal
from io import BytesIO
from tempfile import TemporaryDirectory
from pathlib import Path

from PIL import Image
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import BodyAnalysisRecord, BodyProgressPhoto, Branch, CustomerPortalMember, EmployeeProfile, PatientProfile, VisitAppointment


def jpeg_bytes():
    buffer = BytesIO()
    Image.new('RGB', (500, 700), '#d5dfd0').save(buffer, 'JPEG')
    return buffer.getvalue()


class BodyProgressTests(TestCase):
    @classmethod
    def setUpClass(cls):
        cls._media = TemporaryDirectory()
        cls._override = override_settings(MEDIA_ROOT=cls._media.name)
        cls._override.enable()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._override.disable()
        cls._media.cleanup()

    def setUp(self):
        self.branch = Branch.objects.create(name='آزمایش اسکن')
        self.mine = PatientProfile.objects.create(full_name='مراجع اول', phone='09121111111')
        self.other = PatientProfile.objects.create(full_name='مراجع دوم', phone='09122222222')
        BodyAnalysisRecord.objects.create(patient=self.mine, weight_kg=Decimal('78.5'))
        BodyAnalysisRecord.objects.create(patient=self.other, weight_kg=Decimal('112.0'))
        self.staff_user = User.objects.create_user('scan-photo-staff', password='secure!')
        profile = EmployeeProfile.objects.get(user=self.staff_user)
        profile.role = 'scan_station'
        profile.branch = self.branch
        profile.save(update_fields=['role', 'branch'])

    def verify(self, phone):
        member = CustomerPortalMember.objects.create(phone=phone, referral_code='GLC'+phone[-9:])
        session = self.client.session
        session['gl_customer_member_id'] = member.pk
        session['gl_customer_auth_at'] = timezone.now().timestamp()
        session.save()

    def test_body_requires_verified_customer_session(self):
        response = self.client.get(reverse('customer_body'))
        self.assertEqual(response.status_code, 302)
        self.assertIn('/customer/login/', response['Location'])

    def test_customer_only_sees_own_analysis(self):
        self.verify(self.mine.phone)
        response = self.client.get(reverse('customer_body'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '78.5')
        self.assertNotContains(response, '112.0')
        self.assertEqual(response['Cache-Control'], 'private, no-store')

    def test_photo_is_private_and_not_served_to_another_patient(self):
        photo = BodyProgressPhoto(
            patient=self.other, phase='baseline', angle='front',
            consent_recorded_at=timezone.now(), recorded_by=self.staff_user,
        )
        photo.image.save('photo.jpg', ContentFile(jpeg_bytes()), save=True)
        self.verify(self.mine.phone)
        response = self.client.get(reverse('customer_body_photo', args=[photo.public_id]))
        self.assertEqual(response.status_code, 404)
        self.assertIn('body_progress_private/', photo.image.name)

    @override_settings(BODY_PROGRESS_UPLOAD_ENABLED=True)
    def test_staff_requires_consent_and_real_arrived_appointment(self):
        appointment = VisitAppointment.objects.create(
            branch=self.branch, phone=self.mine.phone, full_name=self.mine.full_name,
            status='arrived', appointment_date=timezone.localdate(), appointment_time=time(10, 0),
        )
        self.client.force_login(self.staff_user)
        url = reverse('body_progress_photo_upload')
        without_consent = self.client.post(url, {
            'appointment_id': appointment.pk, 'phase': 'baseline',
            'front': SimpleUploadedFile('front.jpg', jpeg_bytes(), content_type='image/jpeg'),
        })
        self.assertEqual(without_consent.status_code, 302)
        self.assertFalse(BodyProgressPhoto.objects.exists())
        saved = self.client.post(url, {
            'appointment_id': appointment.pk, 'phase': 'baseline', 'consent': 'yes',
            'front': SimpleUploadedFile('front.jpg', jpeg_bytes(), content_type='image/jpeg'),
        })
        self.assertEqual(saved.status_code, 302)
        photo = BodyProgressPhoto.objects.get()
        self.assertEqual(photo.patient_id, self.mine.pk)
        self.assertEqual(photo.angle, 'front')
        self.assertEqual(photo.phase, 'baseline')
        self.assertTrue(photo.image.name.startswith('body_progress_private/'))

    def test_nginx_config_denies_public_photo_urls(self):
        for name in ('nginx.conf', 'nginx-lan.conf'):
            source = Path(settings.BASE_DIR, 'deploy', name).read_text()
            self.assertIn('body_progress_private', source)
