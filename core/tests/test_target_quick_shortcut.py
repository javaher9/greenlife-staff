"""Navigation smoke checks: owner target orb is active and direct."""
from pathlib import Path
from django.test import SimpleTestCase
from django.urls import reverse
from django.conf import settings


class TargetQuickShortcutTests(SimpleTestCase):
    def test_target_orb_is_an_active_direct_link(self):
        source = (Path(settings.BASE_DIR) / "core/templates/core/base.html").read_text(encoding="utf-8")
        self.assertIn(
            """class="gl-quick-orb gl-quick-targets" href="{% url 'sales_targets_dashboard' %}?shortcut=1" """,
            source,
        )
        self.assertIn("""href="{% url 'lead_management_dashboard' %}?shortcut=1" """, source)
        self.assertIn("""href="{% url 'finance_dashboard' %}?shortcut=1" """, source)
        self.assertEqual(reverse("sales_targets_dashboard"), "/sales-targets/")

    def test_button_styling_is_enabled(self):
        css = (Path(settings.BASE_DIR) / "core/static/core/executive-nav-v1.css").read_text(encoding="utf-8")
        selectors = [line for line in css.splitlines()
                     if line.startswith("body.gl-executive-nav-enabled .gl-quick-targets{")]
        self.assertEqual(len(selectors), 2)
        for line in selectors:
            self.assertIn("opacity:1!important", line)
            self.assertIn("cursor:pointer!important", line)
            self.assertNotIn("not-allowed", line)
