import re


def safe_label(value):
    """Names are free text too: redact phone-like sequences and external links."""
    text = str(value or '')
    text = re.sub(r'(?:https?://|www\.|wa\.me/|tel:|mailto:)\S+', '…', text, flags=re.I)
    text = re.sub(r'(?:\+?\d[\s().\-]*){7,}', '…', text)
    return text[:140]
