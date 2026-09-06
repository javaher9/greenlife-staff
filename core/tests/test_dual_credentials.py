from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from core.credential_security import change_desktop_password, change_mobile_pin, decrypt_secret
from core.models import AuditLog, Branch, EmployeeProfile, StaffCredential


MOBILE_HEADERS={
    'HTTP_USER_AGENT':'Mozilla/5.0 (Linux; Android 16; Pixel 9) AppleWebKit/537.36 Chrome/140 Mobile Safari/537.36',
    'HTTP_SEC_CH_UA_MOBILE':'?1',
}
DESKTOP_HEADERS={
    'HTTP_USER_AGENT':'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/140 Safari/537.36',
}


class DualCredentialTests(TestCase):
    def setUp(self):
        self.branch=Branch.objects.create(name='نیاوران')
        self.admin=User.objects.create_user(
            username='drjavaherian',password='AdminDesktop123',
            first_name='مدیر',last_name='سیستم',
        )
        EmployeeProfile.objects.create(
            user=self.admin,role='admin',branch=self.branch,job_title='مدیر سیستم',is_active=True,
        )
        self.staff=User.objects.create_user(
            username='staff-dual',password='LegacyDesktop123',
            first_name='کارمند',last_name='آزمایشی',
        )
        self.profile=EmployeeProfile.objects.create(
            user=self.staff,role='employee',branch=self.branch,job_title='کارمند',is_active=True,
        )

    def test_mobile_falls_back_to_existing_desktop_password_until_pin_is_set(self):
        response=self.client.post(
            reverse('login'),
            {'username':'STAFF-DUAL','password':'LegacyDesktop123'},
            **MOBILE_HEADERS,
        )
        self.assertRedirects(response,reverse('dashboard'),fetch_redirect_response=False)
        credential=StaffCredential.objects.get(user=self.staff)
        self.assertIsNotNone(credential.last_mobile_login)

    def test_mobile_pin_becomes_independent_from_desktop_password(self):
        change_mobile_pin(self.staff,'123456',actor=self.admin)

        response=self.client.post(
            reverse('login'),
            {'username':'staff-dual','password':'LegacyDesktop123'},
            **MOBILE_HEADERS,
        )
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'نام کاربری یا رمز صحیح نیست.')

        response=self.client.post(
            reverse('login'),
            {'username':'staff-dual','password':'123456'},
            **MOBILE_HEADERS,
        )
        self.assertRedirects(response,reverse('dashboard'),fetch_redirect_response=False)

        self.client.logout()
        response=self.client.post(
            reverse('login'),
            {'username':'staff-dual','password':'LegacyDesktop123'},
            **DESKTOP_HEADERS,
        )
        self.assertRedirects(response,reverse('dashboard'),fetch_redirect_response=False)

    def test_mobile_pin_locks_after_five_failed_attempts(self):
        change_mobile_pin(self.staff,'654321',actor=self.admin)
        for _ in range(5):
            response=self.client.post(
                reverse('login'),
                {'username':'staff-dual','password':'000000'},
                **MOBILE_HEADERS,
            )
        credential=StaffCredential.objects.get(user=self.staff)
        self.assertIsNotNone(credential.mobile_locked_until)
        response=self.client.post(
            reverse('login'),
            {'username':'staff-dual','password':'654321'},
            **MOBILE_HEADERS,
        )
        self.assertContains(response,'ده دقیقه')

    def test_super_admin_can_update_and_reveal_but_regular_staff_cannot(self):
        self.client.force_login(self.admin)
        response=self.client.post(reverse('credential_update',args=[self.profile.pk]),{
            'desktop_password':'NewDesktop123',
            'mobile_pin':'112233',
        })
        self.assertRedirects(response,reverse('credential_settings'))
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password('NewDesktop123'))

        credential=StaffCredential.objects.get(user=self.staff)
        self.assertTrue(check_password('112233',credential.mobile_pin_hash))
        self.assertNotIn('112233',credential.mobile_pin_cipher)
        self.assertNotIn('NewDesktop123',credential.desktop_password_cipher)
        self.assertEqual(decrypt_secret(credential.mobile_pin_cipher),'112233')
        self.assertEqual(decrypt_secret(credential.desktop_password_cipher),'NewDesktop123')

        response=self.client.post(reverse('credential_reveal',args=[self.profile.pk,'desktop']))
        self.assertEqual(response.status_code,200)
        self.assertEqual(response.json()['secret'],'NewDesktop123')
        self.assertTrue(AuditLog.objects.filter(
            actor=self.admin,action='credential_reveal',object_id=str(self.staff.pk)
        ).exists())

        self.client.force_login(self.staff)
        self.assertEqual(self.client.get(reverse('credential_settings')).status_code,403)
        self.assertEqual(
            self.client.post(reverse('credential_reveal',args=[self.profile.pk,'mobile'])).status_code,
            403,
        )

    def test_existing_desktop_password_is_not_recoverable_until_reset_but_still_works(self):
        self.client.force_login(self.admin)
        response=self.client.get(reverse('credential_settings'))
        self.assertEqual(response.status_code,200)
        self.assertContains(response,'قدیمی / ثبت نشده')
        self.client.logout()
        response=self.client.post(
            reverse('login'),
            {'username':'staff-dual','password':'LegacyDesktop123'},
            **DESKTOP_HEADERS,
        )
        self.assertRedirects(response,reverse('dashboard'),fetch_redirect_response=False)

    def test_super_admin_can_view_as_staff_and_return_without_staff_password(self):
        self.client.force_login(self.admin)
        response=self.client.post(reverse('impersonate_start',args=[self.profile.pk]))
        self.assertRedirects(response,reverse('dashboard'),fetch_redirect_response=False)
        self.assertEqual(int(self.client.session['impersonator_user_id']),self.admin.pk)

        response=self.client.get(reverse('dashboard'),**DESKTOP_HEADERS)
        self.assertContains(response,'بازگشت به ادمین')

        response=self.client.post(reverse('impersonate_return'))
        self.assertRedirects(response,reverse('credential_settings'),fetch_redirect_response=False)
        self.assertNotIn('impersonator_user_id',self.client.session)
        response=self.client.get(reverse('credential_settings'))
        self.assertEqual(response.status_code,200)

    def test_setting_mobile_pin_does_not_change_desktop_password(self):
        change_mobile_pin(self.staff,'778899',actor=self.admin)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password('LegacyDesktop123'))

    def test_change_desktop_password_stores_encrypted_recovery_copy(self):
        change_desktop_password(self.staff,'DesktopSafe123',actor=self.admin)
        self.staff.refresh_from_db()
        credential=StaffCredential.objects.get(user=self.staff)
        self.assertTrue(self.staff.check_password('DesktopSafe123'))
        self.assertEqual(decrypt_secret(credential.desktop_password_cipher),'DesktopSafe123')
