from datetime import timedelta
from importlib.util import find_spec
import os
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client
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
        sessions = {}
        for user in (worker, manager):
            client = Client()
            client.force_login(user)
            sessions[user.pk] = client.cookies[settings.SESSION_COOKIE_NAME].value
        with sync_playwright() as driver:
            browser = driver.chromium.launch(executable_path=os.environ.get('PLAQUE_TEST_BROWSER'))
            for user, path in [(worker,'/call-center/follow-ups/?tab=today'), (manager,'/management/all-leads/')]:
                page = browser.new_page(viewport={'width': 1280 if user==worker else 768, 'height': 720})
                page.context.add_cookies([{'name':settings.SESSION_COOKIE_NAME, 'value':sessions[user.pk],'url':self.live_server_url}])
                page.goto(self.live_server_url+path)
                if user == manager:
                    page.locator('.al-plaque .al-disc').filter(has_text='DC').wait_for()
                page.locator('[data-call-plaque-url]').first.click()
                dialog = page.locator('dialog[open]')
                dialog.get_by_text('یادداشت پیگیری قدیمی', exact=True).wait_for()
                if user==worker:
                    dialog.locator('#cpAfterTab').click()
                    dialog.get_by_role('button', name='راهنمای تست دیسک').click()
                    self.assertTrue(dialog.locator('#cpDiscGuide').is_visible())
                    dialog.get_by_role('button', name='راهنمای تست دیسک').click()
                    for letter in ('D', 'I', 'I', 'C'):
                        dialog.locator(f'[data-disc-letter="{letter}"]').click()
                    self.assertEqual(dialog.locator('[data-disc-result]').inner_text(), 'DC')
                    dialog.locator('[data-cp-field=communication_evidence]').fill('درباره جزئیات روش پرسید')
                    for key, stars in [('interest', '4'), ('budget_fit', '2')]:
                        dialog.locator(f'input[name="cp-rating-{key}"][value="{stars}"]').check()
                    dialog.locator('#cpDuringTab').click()
                    self.assertTrue(dialog.locator('input[name="cp-rating-interest"][value="4"]').is_checked())
                    dialog.locator('#cpAfterTab').click()
                    for width in (1280, 768, 390):
                        page.set_viewport_size({'width': width, 'height': 800})
                        area = dialog.locator('[data-cp-assessment]')
                        directory = Path('test-artifacts')
                        directory.mkdir(exist_ok=True)
                        area.locator('.cp-disc').screenshot(path=directory / f'all-leads-disc-{width}.png')
                        ratings = area.locator('[data-cp-stars]')
                        for key, stars in [('interest', '4'), ('budget_fit', '2')]:
                            self.assertTrue(ratings.locator(f'input[name="cp-rating-{key}"][value="{stars}"]').is_checked())
                        ratings.screenshot(path=directory / f'all-leads-call-assessment-{width}.png')
                        self.assertTrue(area.evaluate('(el) => el.scrollWidth <= el.clientWidth + 1'))
                    page.set_viewport_size({'width': 1280, 'height': 800})
                    dialog.locator('[data-cp-field=followup_consent]').select_option('yes')
                    dialog.locator('[data-cp-interval]').select_option('days:2')
                    dialog.locator('[data-cp-field=notes]').fill('پیگیری بعد از سفر')
                    dialog.locator('[data-cp-finalize]').first.click()
                    dialog.locator('.cp-history-item').wait_for()
                else:
                    dialog.locator('.cp-manager-note').filter(has_text='پیگیری بعد از سفر').wait_for()
                    summary = dialog.locator('#cpBefore')
                    for value in ('۴ از ۵', '۲ از ۵', 'DC'):
                        self.assertIn(value, summary.inner_text())
                    self.assertTrue(dialog.locator('#cpBeforeTab').is_visible())
                    self.assertFalse(dialog.locator('[data-cp-finalize]').first.is_visible())
                page.close()
            browser.close()
        lead.refresh_from_db()
        self.assertEqual(lead.next_follow_up, timezone.localdate()+timedelta(days=2))
        self.assertEqual(lead.call_sessions.filter(state='final').count(), 1)
