"""Public sales-network WhatsApp group invitation. Membership is user-initiated."""
from django.conf import settings

DEFAULT_SALES_NETWORK_WHATSAPP_URL = 'https://chat.whatsapp.com/KEXZwgqogbQCaGEUkTZpUa'
SALES_NETWORK_WHATSAPP_URL = getattr(settings, 'SALES_NETWORK_WHATSAPP_URL', DEFAULT_SALES_NETWORK_WHATSAPP_URL)
