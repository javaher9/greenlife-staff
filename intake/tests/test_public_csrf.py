"""Public intake must post anonymously while retaining Django CSRF protection."""
import hashlib
from datetime import time, timedelta

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from core.models import Branch, VisitAppointment
from intake.models import IntakeInvitation


@override_settings(ALLOWED_HOSTS=['testserver', 'app.greenlifeclinics.com'])
class PublicIntakeCsrfTests(TestCase):
    def setUp(self):
        branch = Branch.objects.create(name='CSRF intake test branch')
        appointment = VisitAppointment.objects.create(
            branch=branch, full_name='مراجع تست', phone='09120001111',
            appointment_date=timezone.localdate(), appointment_time=time(10, 30),
            status='arrived',
        )
        self.token = 'public-intake-test-token-that-is-long-enough-12345'
        self.invitation = IntakeInvitation.objects.create(
            appointment=appointment,
            token_hash=hashlib.sha256(self.token.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(hours=1),
        )
        self.url = reverse('intake_public_form', args=[self.token])
        self.client = Client(enforce_csrf_checks=True)

    def _valid_data(self):
        return {
            'reasons': ['کاهش وزن'],
            'screening_confirmed': 'on',
            'consent': 'on',
            'medications': '',
            'allergies': '',
        }

    def test_anonymous_get_then_secure_post_persists_answers(self):
        response = self.client.get(self.url, secure=True, HTTP_HOST='app.greenlifeclinics.com')
        self.assertEqual(response.status_code, 200)
        self.assertIn('csrftoken', response.cookies)
        self.assertContains(response, 'content="same-origin"')
        cookie = self.client.cookies['csrftoken'].value
        posted = self.client.post(
            self.url, self._valid_data(), secure=True, HTTP_HOST='app.greenlifeclinics.com',
            HTTP_REFERER='https://app.greenlifeclinics.com' + self.url,
            HTTP_X_CSRFTOKEN=cookie,
        )
        self.assertEqual(posted.status_code, 200)
        self.invitation.refresh_from_db()
        self.assertIsNotNone(self.invitation.completed_at)
        self.assertEqual(self.invitation.answers['reasons'], ['کاهش وزن'])

    def test_missing_csrf_is_rejected_and_does_not_save(self):
        response = Client(enforce_csrf_checks=True).post(
            self.url, self._valid_data(), secure=True, HTTP_HOST='app.greenlifeclinics.com',
        )
        self.assertEqual(response.status_code, 403)
        self.invitation.refresh_from_db()
        self.assertIsNone(self.invitation.completed_at)
