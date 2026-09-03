from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile

from core.digital_referral_models import DigitalReferralProfile
from core.models import ReferralProfile


class DigitalReferralSignupTests(TestCase):
    def _photo(self):
        # Minimal valid 1x1 GIF; upload field accepts images after Pillow validation.
        return SimpleUploadedFile(
            'person.gif',
            b'GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;',
            content_type='image/gif',
        )

    def test_public_signup_creates_only_digital_profile(self):
        response = self.client.post(
            reverse('digital_referral_signup') + '?source=instagram',
            {
                'source': 'instagram',
                'first_name': 'Test',
                'last_name': 'Member',
                'phone': '09120000000',
                'username': 'digitalmember',
                'password': 'Strong-pass-123',
                'password_confirm': 'Strong-pass-123',
                'consent': 'on',
                'photo': self._photo(),
            },
        )
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username='digitalmember')
        profile = DigitalReferralProfile.objects.get(user=user)
        self.assertEqual(profile.source, 'instagram')
        self.assertFalse(ReferralProfile.objects.filter(user=user).exists())

    def test_source_is_kept_separate(self):
        user = User.objects.create_user(username='siteuser')
        DigitalReferralProfile.objects.create(
            user=user,
            source='drjavaherian',
            phone='09121111111',
            referral_code=DigitalReferralProfile.new_code(),
        )
        self.assertEqual(DigitalReferralProfile.objects.filter(source='drjavaherian').count(), 1)
        self.assertEqual(ReferralProfile.objects.count(), 0)
