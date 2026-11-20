from importlib.util import find_spec
from unittest import skipUnless
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.test import Client, override_settings
from django.urls import reverse
from django.utils import timezone
from core.models import ExecutiveSiteReading


@override_settings(EXECUTIVE_USERNAMES=['board-owner'])
@skipUnless(find_spec('playwright'), 'Requires Playwright')
class BoardBrowserTests(StaticLiveServerTestCase):
    def test_desktop_and_mobile_board_controls(self):
        from playwright.sync_api import sync_playwright
        owner=get_user_model().objects.create_user('board-owner')
        client=Client()
        client.force_login(owner)
        ExecutiveSiteReading.objects.create(domain='rejim.ir', checked_at=timezone.now(), state='down', failures=2)
        with sync_playwright() as driver:
            browser=driver.chromium.launch()
            for width in (390, 1280):
                page=browser.new_page(viewport={'width':width,'height':850}, reduced_motion='reduce')
                page.context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
                page.goto(self.live_server_url+reverse('agent_activity'),wait_until='domcontentloaded')
                board=page.locator('#gl-neon-board')
                self.assertEqual(board.locator('.neon-sites details').count(),5)
                self.assertEqual(board.locator('.neon-pages details').count(),6)
                down=board.locator('.neon-site[data-state=down]')
                down.locator('summary').click()
                self.assertTrue(down.get_by_text('آمار بازدید در دسترس نیست.').is_visible())
                self.assertTrue(down.locator('.neon-beacon').is_visible())
                board.locator('.neon-network summary').click()
                self.assertTrue(board.get_by_role('link',name='مشاهدهٔ شبکهٔ فروش').is_visible())
                self.assertTrue(board.evaluate('(el)=>el.scrollWidth <= el.clientWidth+1'))
                from pathlib import Path
                Path('test-artifacts').mkdir(exist_ok=True)
                board.locator('section').first.screenshot(path=f'test-artifacts/all-leads-executive-sites-{width}.png')
                page.close()
            browser.close()
