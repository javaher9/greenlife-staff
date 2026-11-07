"""Protect the external hostname on the IIS -> nginx -> Django login path."""
from pathlib import Path
from django.conf import settings
from django.test import SimpleTestCase


class PublicHostProxyTests(SimpleTestCase):
    def test_nginx_keeps_browser_hostname(self):
        conf=(Path(settings.BASE_DIR)/'deploy/nginx.conf').read_text(encoding='utf-8')
        self.assertIn('server_name staff.greenlifeclinics.com app.greenlifeclinics.com;',conf)
        self.assertIn('proxy_set_header Host $host;',conf)
        self.assertNotIn('proxy_set_header Host staff.greenlifeclinics.com;',conf)
        self.assertIn('proxy_set_header X-Forwarded-Proto $greenlife_forwarded_proto;',conf)

    def test_app_login_trusts_https_origin_without_disabling_csrf(self):
        self.assertIn('app.greenlifeclinics.com',settings.ALLOWED_HOSTS)
        self.assertIn('https://app.greenlifeclinics.com',settings.CSRF_TRUSTED_ORIGINS)
        self.assertIn('django.middleware.csrf.CsrfViewMiddleware',settings.MIDDLEWARE)
        # Cookie flags are environment-specific; Django CSRF remains mandatory.
