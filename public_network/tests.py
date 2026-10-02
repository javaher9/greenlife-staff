from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from .models import PublicNetworkMember
from core.models import ReferralLead


PNG_1X1 = (
    b'\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01'
    b'\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82'
)


class PublicNetworkTests(TestCase):
    def photo(self, name='p.png'):
        return SimpleUploadedFile(name, PNG_1X1, content_type='image/png')

    def signup_payload(self, username='member1', phone='09121234567'):
        return {
            'first_name': 'علی',
            'last_name': 'آزمایشی',
            'phone': phone,
            'username': username,
            'password': 'StrongPass123',
            'password_confirm': 'StrongPass123',
            'photo': self.photo(),
            'accept_terms': 'on',
            'src': 'story',
        }

    def test_story_signup_creates_isolated_member_and_logs_in(self):
        response = self.client.post(reverse('public_network:signup') + '?src=story', self.signup_payload())
        self.assertRedirects(response, reverse('public_network:dashboard'))
        member = PublicNetworkMember.objects.get(user__username='member1')
        self.assertEqual(member.source, 'story')
        self.assertEqual(member.country.code, 'IR')
        self.assertEqual(member.preferred_language, 'fa')
        self.assertIsNone(member.sponsor)
        self.assertFalse(hasattr(member.user, 'profile'))

    def test_referral_link_attaches_sponsor(self):
        sponsor_user = User.objects.create_user('sponsor', password='StrongPass123', first_name='Sara')
        sponsor = PublicNetworkMember.objects.create(user=sponsor_user, phone='+989121111111', photo=self.photo('s.png'))
        payload = self.signup_payload(username='child', phone='09122222222')
        payload['src'] = 'referral'
        response = self.client.post(reverse('public_network:signup_with_code', args=[sponsor.code]), payload)
        self.assertRedirects(response, reverse('public_network:dashboard'))
        child = PublicNetworkMember.objects.get(user__username='child')
        self.assertEqual(child.sponsor, sponsor)
        self.assertEqual(child.source, 'referral')

    def test_public_member_is_redirected_away_from_staff_root(self):
        user = User.objects.create_user('publicuser', password='StrongPass123')
        PublicNetworkMember.objects.create(user=user, phone='+989123333333', photo=self.photo('u.png'))
        self.client.login(username='publicuser', password='StrongPass123')
        response = self.client.get('/')
        self.assertRedirects(response, reverse('public_network:dashboard'))


    def test_turkey_signup_creates_bilingual_member_and_call_center_lead(self):
        payload = {
            'first_name': 'Deniz',
            'last_name': 'Yilmaz',
            'phone': '0532 123 45 67',
            'username': 'deniztr',
            'password': 'StrongPass123',
            'password_confirm': 'StrongPass123',
            'photo': self.photo('tr.png'),
            'accept_terms': 'on',
            'src': 'direct',
        }
        response = self.client.post(reverse('public_network:turkey_signup'), payload)
        self.assertRedirects(response, reverse('public_network:turkey_dashboard'))
        member = PublicNetworkMember.objects.get(user__username='deniztr')
        self.assertEqual(member.phone, '+905321234567')
        self.assertEqual(member.country.code, 'TR')
        self.assertEqual(member.preferred_language, 'tr')
        lead = ReferralLead.objects.get(phone='+905321234567')
        self.assertEqual(lead.country.code, 'TR')
        self.assertEqual(lead.preferred_language, 'tr')
        self.assertIn('[market:turkey]', lead.notes)
        self.assertEqual(lead.interested_service, 'Türkiye Network Marketing')
        self.assertIn('/tr/network/', lead.source_url)

    def test_turkey_dashboard_uses_turkey_invite_link(self):
        user = User.objects.create_user('turkeymember', password='StrongPass123', first_name='Ada')
        member = PublicNetworkMember.objects.create(
            user=user, phone='+905551111111', photo=self.photo('ada.png')
        )
        self.client.login(username='turkeymember', password='StrongPass123')
        response = self.client.get(reverse('public_network:turkey_dashboard'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, reverse('public_network:turkey_signup_with_code', args=[member.code]))


    def test_turkey_language_switch_renders_single_language_copy(self):
        tr_response = self.client.get(reverse('public_network:turkey_signup') + '?lang=tr')
        self.assertEqual(tr_response.status_code, 200)
        self.assertContains(tr_response, 'Hesap oluştur')
        self.assertNotContains(tr_response, 'Build your network.')

        en_response = self.client.get(reverse('public_network:turkey_signup') + '?lang=en')
        self.assertEqual(en_response.status_code, 200)
        self.assertContains(en_response, 'Create account')
        self.assertContains(en_response, 'Build your network.')
        self.assertNotContains(en_response, 'Ağını kur.')

    def test_english_turkey_signup_persists_language_on_member_and_lead(self):
        payload = {
            'first_name': 'Ece',
            'last_name': 'English',
            'phone': '0555 444 33 22',
            'username': 'eceenglish',
            'password': 'StrongPass123',
            'password_confirm': 'StrongPass123',
            'photo': self.photo('ece.png'),
            'accept_terms': 'on',
            'src': 'direct',
            'lang': 'en',
        }
        response = self.client.post(reverse('public_network:turkey_signup'), payload)
        self.assertRedirects(response, reverse('public_network:turkey_dashboard') + '?lang=en')
        member = PublicNetworkMember.objects.get(user__username='eceenglish')
        lead = ReferralLead.objects.get(phone='+905554443322')
        self.assertEqual(member.preferred_language, 'en')
        self.assertEqual(lead.preferred_language, 'en')
