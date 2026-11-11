"""Run explicitly with RUN_IM_BROWSER=1; uses synthetic users only."""
import os
from pathlib import Path
from unittest import skipUnless
from django.contrib.auth.models import User
from django.contrib.staticfiles.testing import StaticLiveServerTestCase
from django.conf import settings
from django.utils import timezone
from core.models import Branch, EmployeeProfile, LeaveRequest


@skipUnless(os.environ.get('RUN_IM_BROWSER')=='1','Explicit browser run')
class InternalManagerBrowserTests(StaticLiveServerTestCase):
    def test_responsive_dashboard_and_leave_detail(self):
        from playwright.sync_api import sync_playwright
        b=Branch.objects.create(name='مرکز آزمایشی')
        owner=User.objects.create_user('demo-internal',first_name='مدیر',last_name='آزمایشی')
        worker=User.objects.create_user('demo-worker',first_name='کارمند',last_name='آزمایشی')
        EmployeeProfile.objects.filter(user=owner).update(role='internal_manager',branch=b,country=b.country)
        EmployeeProfile.objects.filter(user=worker).update(role='call_center',branch=b,country=b.country)
        leave=LeaveRequest.objects.create(user=worker,start_date=timezone.localdate(),end_date=timezone.localdate(),reason='درخواست آزمایشی برای بررسی رابط')
        self.client.force_login(owner)
        out=Path(os.environ.get('IM_ARTIFACTS','/workspace/scratch/f21f6e9c16f0/im-artifacts'));out.mkdir(exist_ok=True,parents=True)
        with sync_playwright() as p:
            launch={'executable_path':os.environ['IM_BROWSER_EXECUTABLE']} if os.environ.get('IM_BROWSER_EXECUTABLE') else {}
            browser=p.chromium.launch(**launch)
            context=browser.new_context()
            context.add_cookies([{'name':settings.SESSION_COOKIE_NAME,'value':self.client.cookies[settings.SESSION_COOKIE_NAME].value,'url':self.live_server_url}])
            page=context.new_page();errors=[]
            page.on('pageerror',lambda exc:errors.append(str(exc)))
            for width,height,label in [(1440,1000,'laptop'),(820,1180,'tablet'),(390,844,'mobile')]:
                page.set_viewport_size({'width':width,'height':height})
                page.goto(self.live_server_url+'/live/');page.locator('.im').wait_for()
                self.assertEqual(page.locator('.im h1').inner_text(),'مدیریت داخلی · پیگیری امروز')
                page.screenshot(path=str(out/f'internal-manager-{label}.png'),full_page=True)
                overflow=page.evaluate('''() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,offenders:[...document.querySelectorAll('body *')].filter(e=>{const r=e.getBoundingClientRect();return r.width && (r.right>innerWidth+1 || r.left < -1)}).slice(0,20).map(e=>({tag:e.tagName,cls:e.className,left:e.getBoundingClientRect().left,right:e.getBoundingClientRect().right}))})''')
                self.assertLessEqual(overflow['scroll'],width+1,overflow)
                if label=='mobile':
                    self.assertFalse(page.locator('.app-sidebar').is_visible())
                    page.locator('.im-menu-toggle').click()
                    self.assertTrue(page.locator('.app-sidebar').is_visible())
                    page.keyboard.press('Escape')
                    self.assertFalse(page.locator('.app-sidebar').is_visible())
            page.goto(self.live_server_url+f'/requests/{leave.pk}/review/')
            self.assertIn('درخواست آزمایشی',page.locator('body').inner_text())
            self.assertFalse(errors,errors)
            browser.close()
