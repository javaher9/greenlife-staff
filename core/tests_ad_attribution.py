"""Regression checks for organic page links and tagged advertising sources."""
from types import SimpleNamespace

from django.test import SimpleTestCase

from .call_center_identity import FlowerLeadProxy
from .instagram_ad_attribution import (
    advertising_source_label,
    normalize_ad_page,
)


def fake_lead(*, url, notes, source='link'):
    return SimpleNamespace(
        notes=notes, source_url=url, group=None, source=source, referrer=None,
    )


class InstagramAdAttributionTests(SimpleTestCase):
    def test_single_generic_ad_link_does_not_invent_a_page(self):
        lead = fake_lead(
            url='https://staff.greenlifeclinics.com/instagram/ads/',
            notes='ورودی تبلیغات اینستاگرام | [entry:advertising]',
        )
        proxy = FlowerLeadProxy(lead)
        self.assertEqual(advertising_source_label(lead), 'تبلیغات')
        self.assertEqual(proxy.lead_group_display, 'اینستاگرام - لینک')
        self.assertEqual(proxy.source_page_display, 'تبلیغات')

    def test_named_external_ad_page_is_shown_in_source_only(self):
        lead = fake_lead(
            url='https://staff.greenlifeclinics.com/instagram/ads/?ad_page=zanashooei',
            notes='ورودی تبلیغات | [entry:advertising] [ad_page:zanashooei]',
        )
        proxy = FlowerLeadProxy(lead)
        self.assertEqual(proxy.lead_group_display, 'اینستاگرام - لینک')
        self.assertEqual(proxy.source_page_display, 'تبلیغات · @zanashooei')

    def test_attribution_survives_old_query_only_links(self):
        lead = fake_lead(
            url='https://staff.greenlifeclinics.com/instagram/ads/?ad_page=greenlife_cafe',
            notes='ورودی تبلیغات | [entry:advertising]',
        )
        self.assertEqual(advertising_source_label(lead), 'تبلیغات · @greenlife_cafe')

    def test_organic_page_is_not_treated_as_advertising(self):
        lead = fake_lead(
            url='https://staff.greenlifeclinics.com/instagram/fast/?source=drjavaherian',
            notes='ورودی مستقیم فرم اینستاگرام | [instagram_page:drjavaherian]',
        )
        proxy = FlowerLeadProxy(lead)
        self.assertEqual(proxy.lead_group_display, 'اینستاگرام - لینک')
        self.assertEqual(proxy.source_page_display, 'Drjavaherian')

    def test_extract_handle_from_instagram_url(self):
        self.assertEqual(
            normalize_ad_page('https://www.instagram.com/zanashooei/?utm_source=test'),
            'zanashooei',
        )
        self.assertEqual(normalize_ad_page('@beauty.page'), 'beauty.page')
        self.assertEqual(normalize_ad_page('پیج زناشویی'), 'پیج زناشویی')
