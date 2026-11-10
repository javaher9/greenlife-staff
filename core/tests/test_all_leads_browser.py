"""Visual/interaction checks run against a disposable CI database only."""
from importlib.util import find_spec
from pathlib import Path
from unittest import skipUnless

from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase

from core.models import EmployeeProfile, ReferralLead, ReferralProfile


@skipUnless(find_spec('playwright'), 'Playwright is installed by the archive CI workflow')
class ArchiveBrowserTests(StaticLiveServerTestCase):
    def test_desktop_mobile_filters_and_virtual_scroll(self):
        from playwright.sync_api import sync_playwright
        manager = User.objects.create_user('archive-browser-manager')
        EmployeeProfile.objects.filter(user=manager).update(role='admin')
        worker = User.objects.create_user('tavana')
        flower = worker.profile
        flower.role = 'call_center'
        flower.save()
        referrer, _ = ReferralProfile.objects.get_or_create(user=manager, defaults={'referral_code': 'browser-test'})
        ReferralLead.objects.bulk_create([
            ReferralLead(referrer=referrer, full_name=('سمانه اکبری' if i == 0 else f'مریم احمدی {i}'), phone=f'0912456{i:04d}', assigned_to=flower, contact_result=('no_answer' if i % 3 else ''), status=('contacted' if i % 3 else 'new'))
            for i in range(300)
        ])
        self.client.force_login(manager)
        out = Path('test-artifacts'); out.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.add_cookies([{'name': settings.SESSION_COOKIE_NAME, 'value': self.client.cookies[settings.SESSION_COOKIE_NAME].value, 'url': self.live_server_url}])
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.goto(self.live_server_url + '/management/all-leads/')
            page.locator('.al-plaque').first.wait_for()
            self.assertEqual(page.locator('.al-heading').evaluate('(el)=>getComputedStyle(el).backgroundColor'), 'rgba(0, 0, 0, 0)')
            self.assertLessEqual(page.locator('input[name=untouched]').bounding_box()['width'], 16)
            page.screenshot(path=str(out / 'all-leads-desktop.png'), full_page=True)
            self.assertLess(page.locator('.al-plaque').count(), 120)
            page.locator('select[name=state]').select_option('new')
            page.wait_for_function("[...document.querySelectorAll('.al-state')].length && [...document.querySelectorAll('.al-state')].every(x=>x.textContent==='جدید')")
            page.locator('select[name=state]').select_option('')
            page.locator('input[name=q]').fill('سمانه اکبری')
            page.wait_for_function("document.querySelectorAll('.al-plaque').length===1")
            self.assertEqual(page.locator('.al-flower').inner_text(), 'بنفشه')
            page.locator('input[name=q]').fill('')
            page.wait_for_function("document.querySelectorAll('.al-plaque').length>1")
            # One user scroll must settle, not repeatedly anchor to replaced rows.
            scroller = page.locator('#al-scroll')
            scroller.evaluate('(el)=>el.scrollTop=500')
            page.wait_for_timeout(1000)
            self.assertAlmostEqual(scroller.evaluate('(el)=>el.scrollTop'), 500, delta=1)
            page.wait_for_timeout(1500)
            self.assertAlmostEqual(scroller.evaluate('(el)=>el.scrollTop'), 500, delta=1)
            self.assertIn('۱۲۰', page.locator('#al-message').inner_text())
            page.locator('#al-scroll').evaluate('(el)=>el.scrollTop=el.scrollHeight')
            page.wait_for_function("document.querySelector('#al-message').textContent.includes('۲۴۰')")
            settled_top = scroller.evaluate('(el)=>el.scrollTop')
            page.wait_for_timeout(1500)
            self.assertAlmostEqual(scroller.evaluate('(el)=>el.scrollTop'), settled_top, delta=1)
            self.assertIn('۲۴۰', page.locator('#al-message').inner_text())
            scroller.evaluate('(el)=>el.scrollTop=300')
            page.wait_for_timeout(1000)
            self.assertAlmostEqual(scroller.evaluate('(el)=>el.scrollTop'), 300, delta=1)
            self.assertLess(page.locator('.al-plaque').count(), 120)
            page.set_viewport_size({'width': 390, 'height': 844})
            page.locator('#al-scroll').evaluate('(el)=>el.scrollTop=0')
            page.screenshot(path=str(out / 'all-leads-mobile.png'), full_page=True)
            self.assertTrue(page.locator('#all-leads').evaluate('(el)=>el.scrollWidth<=el.clientWidth+2'))
            self.assertTrue(page.locator('.al-plaque').first.evaluate('(el)=>el.scrollWidth<=el.clientWidth+2'))
            self.assertEqual(errors, [])
            browser.close()
