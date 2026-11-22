from hashlib import sha256
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from core.models import PhoneVoiceSample


class PhoneVoiceSampleTests(TestCase):
    def test_private_playback_and_range(self):
        url = reverse('phone_voice_sample', args=['yasaman'])
        PhoneVoiceSample.objects.create(assistant='yasaman', contents=b'RIFFtestWAVE')
        self.assertEqual(self.client.get(url).status_code, 302)
        user = get_user_model().objects.create_user(username='voice-listener')
        self.client.force_login(user)
        self.assertEqual(self.client.get(url).status_code, 403)
        admin = get_user_model().objects.create_superuser(username='voice-admin')
        self.client.force_login(admin)
        response = self.client.get(url, HTTP_RANGE='bytes=0-3')
        self.assertEqual(response.status_code, 206)
        self.assertEqual(response.content, b'RIFF')
        self.assertEqual(response.headers['Content-Range'], 'bytes 0-3/12')
        self.assertIn('no-store', response.headers['Cache-Control'])
        self.assertContains(self.client.get(reverse('phone_center')), f'src="{url}"')

    def test_install_accepts_only_approved_bytes_once(self):
        token = 'a' * 64
        url = reverse('phone_voice_sample_install', args=['yasaman'])
        approved = b'RIFFtestWAVE'
        with patch('core.phone_voice_samples._IMPORT_TOKEN_HASH', sha256(token.encode()).hexdigest()), patch(
            'core.phone_voice_samples._APPROVED', {'yasaman': sha256(approved).hexdigest()}
        ):
            self.assertEqual(self.client.post(url, approved, content_type='audio/wav').status_code, 404)
            headers = {'HTTP_AUTHORIZATION': 'Bearer ' + token}
            self.assertEqual(self.client.post(url, b'other', content_type='audio/wav', **headers).status_code, 400)
            self.assertEqual(self.client.post(url, approved, content_type='audio/wav', **headers).status_code, 201)
            self.assertEqual(self.client.post(url, approved, content_type='audio/wav', **headers).status_code, 409)
