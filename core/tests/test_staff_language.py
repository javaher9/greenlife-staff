from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.localized_response import localize_html_exact
from core.models import Branch, Country, EmployeeProfile


class StaffLanguageEngineTests(TestCase):
    def setUp(self):
        self.iran=Country.objects.get(code='IR')
        self.branch=Branch.objects.create(name='Language Test Branch',country=self.iran)
        self.user=User.objects.create_user('language-user',password='StrongPass123',first_name='Test')
        self.profile=EmployeeProfile.objects.create(
            user=self.user,
            role='employee',
            country=self.iran,
            branch=self.branch,
            preferred_language='fa',
        )

    def test_anonymous_language_switch_is_allowed_and_persists_in_session(self):
        response=self.client.post(
            reverse('language_switch'),
            {'language':'tr','next':reverse('login')},
        )
        self.assertRedirects(response,reverse('login'))
        self.assertEqual(self.client.session.get('greenlife_ui_language'),'tr')

        response=self.client.get(reverse('login'))
        self.assertContains(response,'Personel sistemine giriş')
        self.assertContains(response,'Kullanıcı adı')

    def test_authenticated_language_switch_persists_on_profile(self):
        self.client.login(username='language-user',password='StrongPass123')
        response=self.client.post(
            reverse('language_switch'),
            {'language':'en','next':reverse('dashboard')},
        )
        self.assertRedirects(response,reverse('dashboard'))
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.preferred_language,'en')
        self.assertEqual(self.client.session.get('greenlife_ui_language'),'en')

    def test_invalid_language_does_not_change_active_language(self):
        self.client.login(username='language-user',password='StrongPass123')
        session=self.client.session
        session['greenlife_ui_language']='tr'
        session.save()

        self.client.post(
            reverse('language_switch'),
            {'language':'de','next':reverse('dashboard')},
        )
        self.assertEqual(self.client.session.get('greenlife_ui_language'),'tr')

    def test_exact_static_fallback_translates_known_ui_copy(self):
        html='<div><h1>مرکز اقدام مدیر</h1><button title="ذخیره">ذخیره</button></div>'
        localized=localize_html_exact(html,'tr')
        self.assertIn('Yönetici Aksiyon Merkezi',localized)
        self.assertIn('Kaydet',localized)
        self.assertNotIn('مرکز اقدام مدیر',localized)

    def test_fallback_does_not_translate_substrings_or_script_content(self):
        html=(
            '<div>یادداشت کاربر: امروز جلسه داشتم</div>'
            '<script>const label="امروز";</script>'
            '<textarea>امروز</textarea>'
        )
        localized=localize_html_exact(html,'en')
        self.assertIn('یادداشت کاربر: امروز جلسه داشتم',localized)
        self.assertIn('const label="امروز"',localized)
        self.assertIn('<textarea>امروز</textarea>',localized)
