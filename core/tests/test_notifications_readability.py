"""Static UI regression for the notifications screen; no database or external effects."""
import re
from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


class NotificationsReadabilityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.html = Path(
            get_template("core/notifications.html").origin.name
        ).read_text(encoding="utf-8")

    def test_small_notification_text_has_readable_floor(self):
        css = self.html.split("<style>", 1)[1].split("</style>", 1)[0]
        for selector, minimum in (
            (".notif-head p", 12),
            (".notif-item strong", 13),
            (".notif-item p", 12),
            (".notif-item small", 11),
            (".notif-empty", 12),
        ):
            match = re.search(
                rf"{re.escape(selector)}\{{[^}}]*?font-size:(\d+)px",
                css,
            )
            self.assertIsNotNone(match, selector)
            self.assertGreaterEqual(int(match.group(1)), minimum, selector)
        self.assertIn("font:900 12px Tahoma", css)
        self.assertIn(".notif-item small{display:block;color:#607282", css)

    def test_notification_actions_and_rtl_inheritance_unchanged(self):
        self.assertIn('class="notif-page"', self.html)
        self.assertIn('method="post"', self.html)
        self.assertIn("{% csrf_token %}", self.html)
        self.assertIn("{% for n in notifications %}", self.html)
        self.assertIn("@media(max-width:700px)", self.html)
