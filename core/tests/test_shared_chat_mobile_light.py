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

    def test_shared_chat_text_readability_floor(self):
        html=Path(get_template('core/_live_chat_widget.html').origin.name).read_text(encoding='utf-8')
        marker='/* Shared staff chat: readable Persian text on desktop and phones. */'
        self.assertEqual(html.count(marker), 1)
        final_css=html.split(marker, 1)[1].split('</style>', 1)[0]
        for rule in (
            '#glLiveChat .gl-live-chat-title small{font-size:11px}',
            '#glLiveChat .gl-live-chat-contact b{font-size:10px}',
            '#glLiveChat .gl-live-chat-contact small{font-size:10px}',
            '#glLiveChat .gl-live-chat-person strong{font-size:12px}',
            '#glLiveChat .gl-live-chat-person small{font-size:10px}',
            '#glLiveChat .gl-live-chat-bubble b{font-size:10px}',
            '#glLiveChat .gl-live-chat-bubble p{font-size:12px;line-height:1.75}',
            '#glLiveChat .gl-live-chat-bubble small{font-size:10px}',
            '#glLiveChat .gl-live-chat-compose textarea,#glLiveChat .gl-live-chat-compose button{font-size:12px}',
        ):
            self.assertIn(rule, final_css)
        self.assertLess(html.index(marker), html.index('</style>'))
