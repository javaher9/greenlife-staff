from django.test import SimpleTestCase
from core.intake_summary import compact_medical_summary


class IntakeMedicalSummaryTests(SimpleTestCase):
    def test_positive_only(self):
        data = compact_medical_summary({
            "conditions": ["دیابت", "خیر", "کم کاری تیروئید"],
            "medications": ["لووتیروکسین"],
            "allergies": ["ندارد"],
            "required_screening_complete": True,
        })
        self.assertEqual(data["sections"]["بیماری‌ها"], ["دیابت", "کم کاری تیروئید"])
        self.assertEqual(data["sections"]["داروها"], ["لووتیروکسین"])
        self.assertNotIn("حساسیت‌ها", data["sections"])
        self.assertFalse(data["screening_incomplete"])

    def test_unanswered_is_not_negative(self):
        data = compact_medical_summary({})
        self.assertEqual(data["sections"], {})
        self.assertTrue(data["screening_incomplete"])

    def test_explicit_negatives_are_hidden(self):
        data = compact_medical_summary({
            "conditions": ["خیر", "هیچ‌کدام"],
            "medications": "ندارد",
            "allergies": None,
            "required_screening_complete": True,
        })
        self.assertEqual(data["sections"], {})
        self.assertFalse(data["screening_incomplete"])
