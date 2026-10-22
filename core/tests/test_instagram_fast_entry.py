from django.test import SimpleTestCase
from django.urls import resolve, reverse
from core.instagram_views import instagram_lead


class InstagramFastEntryRoutingTests(SimpleTestCase):
    def test_fast_entry_uses_existing_crm_intake(self):
        self.assertEqual(reverse('instagram_fast_lead'), '/instagram/fast/')
        self.assertIs(resolve('/instagram/fast/').func, instagram_lead)
        self.assertIs(resolve('/instagram/').func, instagram_lead)
