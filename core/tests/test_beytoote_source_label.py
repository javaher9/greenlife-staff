from types import SimpleNamespace

from django.test import SimpleTestCase

from core.call_center_identity import FlowerLeadProxy


class BeytooteSourceLabelTests(SimpleTestCase):
    def test_beytoote_route_is_shown_as_beytoote_not_greenlife(self):
        lead=SimpleNamespace(
            source_url='https://staff.greenlifeclinics.com/beytoote/',
            source='qr',
            notes='',
            group=None,
            referrer=None,
            assigned_to_id=None,
            get_source_display=lambda: 'QR',
        )
        proxy=FlowerLeadProxy(lead)
        self.assertEqual(proxy.source_page_display,'بیتوته')
