from datetime import timedelta
from importlib.util import find_spec
import os
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.utils import timezone

from core.models import ReferralLead, ReferralProfile


@skipUnless(find_spec('playwright'), 'Requires Playwright')
class UnifiedCallBrowserTests(StaticLiveServerTestCase):
    def test_existing_callback_to_manager_summary(self):
        from playwright.sync_api import sync_playwright

        manager = User.objects.create_superuser('plaque-manager')
        worker = User.objects.create_user('plaque-worker')
        worker.profile.role = 'call_center'
        worker.profile.save()
        referrer, _ = ReferralProfile.objects.get_or_create(user=manager, defaults={'referral_code':'plaque-browser'})
        lead = ReferralLead.objects.create(full_name='تست یکپارچگی', phone='09120000001',
            referrer=referrer, assigned_to=worker.profile, status='contacted', contact_result='follow_up',
            next_follow_up=timezone.localdate(), notes='یادداشت پیگیری قدیمی')
        with sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=os.environ.get('PLAQUE_TEST_BROWSER'))
            for user, path in [(worker,'/call-center/follow-ups/?tab=today'), (manager,'/management/all-leads/')]:
                self.client.force_login(user)
                page = browser.new_page(viewport={'width': 1280 if user==worker else 768, 'height': 720})
                page.context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
                page.goto(self.live_server_url+path)
                page.locator('[data-call-plaque-url]').first.click()
                dialog = page.locator('dialog[open]')
                dialog.get_by_text('یادداشت پیگیری قدیمی', exact=True).wait_for()
                if user==worker:
                    dialog.locator('#cpAfterTab').click()
                    dialog.locator('[data-cp-field=followup_consent]').select_option('yes')
                    dialog.locator('[data-cp-interval]').select_option('days:2')
                    dialog.locator('[data-cp-field=notes]').fill('پیگیری بعد از سفر')
                    dialog.locator('[data-cp-finalize]').first.click()
                    dialog.locator('.cp-history-item').wait_for()
                    lead.refresh_from_db()
                    self.assertEqual(lead.next_follow_up, timezone.localdate()+timedelta(days=2))
                    self.assertEqual(lead.call_sessions.filter(state='final').count(), 1)
                else:
                    dialog.get_by_text('پیگیری بعد از سفر', exact=True).wait_for()
                    self.assertTrue(dialog.locator('#cpBeforeTab').is_visible())
                    self.assertFalse(dialog.locator('[data-cp-finalize]').first.is_visible())
                page.close()
            browser.close()
