"""Guard light mobile staff chat; no patient data or gateway calls."""
from pathlib import Path
from django.template.loader import get_template
from django.test import SimpleTestCase


class MobileStaffChatLightTests(SimpleTestCase):
    def test_phone_chat_does_not_use_dark_surfaces(self):
        html=Path(get_template('core/_live_chat_widget.html').origin.name).read_text(encoding='utf-8')
        marker='/* Phone chat: light palette only; keep existing positioning and interactions. */'
        self.assertIn(marker, html)
        mobile=html.split(marker,1)[1].split('</style>',1)[0]
        self.assertIn('@media(max-width:700px){',mobile)
        self.assertIn('.gl-live-chat-drawer{background:#fff;',mobile)
        self.assertIn('.gl-live-chat-thread{background:#fff}',mobile)
        self.assertIn('.gl-live-chat-compose textarea{background:#f7fbf8;',mobile)
        self.assertIn('.gl-live-chat-bubble.mine{background:#e6f5ec;',mobile)
        self.assertNotIn('background:#0b141e', mobile)

    def test_chat_controls_remain_intact(self):
        html=Path(get_template('core/_live_chat_widget.html').origin.name).read_text(encoding='utf-8')
        for identifier in ('glLiveChatLauncher','glLiveChatDrawer','glLiveChatContacts',
                           'glLiveChatInput','glLiveChatSend'):
            self.assertIn('id="'+identifier+'"',html)
