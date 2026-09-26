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
        self.assertEqual(proxy.lead_group_display,'بنر - سلامت')

    def test_beytoote_reportage_start_is_separate_from_banner(self):
        lead=SimpleNamespace(
            source_url='https://greenlifeclinics.com/?utm_source=beytoote&utm_medium=reportage&utm_campaign=belly-fat-reportage&utm_content=start-slimming#passport',
            source='link',
            notes='[channel:website] [campaign:belly-fat-reportage]',
            group=None,
            referrer=None,
            assigned_to_id=None,
            get_source_display=lambda: 'لینک اختصاصی',
        )
        proxy=FlowerLeadProxy(lead)
        self.assertEqual(proxy.source_page_display,'بیتوته')
        self.assertEqual(proxy.lead_group_display,'رپورتاژ - استارت')

