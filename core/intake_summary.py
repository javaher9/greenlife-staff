"""Presentation rules for consented patient intake answers.

Do not equate missing answers with explicit negative answers.
Keep raw clinical answers in their authorized medical record; only return
positive/clinically relevant entries for the compact physician summary.
"""
from collections.abc import Mapping


NEGATIVE = {"", "no", "false", "none", "0", "خیر", "ندارد", "هیچ‌کدام", "هیچ کدام"}
POSITIVE = {"yes", "true", "1", "بله"}


def _meaningful(value):
    if value is None or value is False:
        return False
    if isinstance(value, str):
        return value.strip().casefold() not in NEGATIVE
    if isinstance(value, (list, tuple, set)):
        return any(_meaningful(item) for item in value)
    if isinstance(value, Mapping):
        return any(_meaningful(item) for item in value.values())
    return bool(value)


def _items(value):
    if not _meaningful(value):
        return []
    if isinstance(value, str):
        return [value.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if _meaningful(item)]
    return [str(value)]


def compact_medical_summary(answers):
    """Return only affirmative clinical data, with an explicit incomplete flag.

    Expected canonical intake keys:
      conditions, medications, allergies, safety_flags, required_screening_complete
    Unknown conditions are NEVER treated as 'no'.
    """
    answers = answers if isinstance(answers, Mapping) else {}
    sections = {
        "بیماری‌ها": _items(answers.get("conditions")),
        "داروها": _items(answers.get("medications")),
        "حساسیت‌ها": _items(answers.get("allergies")),
        "هشدارهای ایمنی": _items(answers.get("safety_flags")),
    }
    return {
        "sections": {label: values for label, values in sections.items() if values},
        "screening_incomplete": answers.get("required_screening_complete") is not True,
    }
