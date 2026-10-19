"""The doctor and patient 360 must only surface the six scan-station metrics."""
from decimal import Decimal
from types import SimpleNamespace
from django.test import SimpleTestCase
from core.scan_analysis_display import SCAN_FIELDS, scan_value, scan_summary, scan_history_rows
from core.doctor_views import _metric_card


class SixScanFieldDisplayTests(SimpleTestCase):
    def test_canonical_fields_are_exactly_scan_station_fields(self):
        from core.scan_station_views import FIELDS
        self.assertEqual([field for field,_,_ in SCAN_FIELDS],[field for field,_ in FIELDS])
        self.assertEqual(len(SCAN_FIELDS),6)
        self.assertNotIn('bmi',[key for key,_,_ in SCAN_FIELDS])
        self.assertNotIn('body_fat_percent',[key for key,_,_ in SCAN_FIELDS])

    def test_json_fat_and_whr_and_historic_blanks_are_safe(self):
        record=SimpleNamespace(
            pk=5,recorded_at=None,weight_kg=Decimal('81.5'),
            inbody_score=Decimal('70'),skeletal_muscle_kg=Decimal('31'),
            visceral_fat=Decimal('9'),measurements={'fat_kg':'23.5','whr':'0.91'},
        )
        self.assertEqual(scan_value(record,'fat_kg'),Decimal('23.5'))
        self.assertEqual(scan_value(record,'whr'),Decimal('0.91'))
        self.assertEqual(len(scan_summary(record)),6)
        self.assertEqual(len(scan_history_rows([record])[0]['metrics']),6)
        old=SimpleNamespace(pk=6,recorded_at=None,weight_kg=Decimal('80.2'),
            inbody_score=None,skeletal_muscle_kg=None,visceral_fat=None,measurements={})
        self.assertIsNone(scan_value(old,'fat_kg'))
        self.assertIsNone(scan_value(old,'whr'))
        self.assertIsNone(_metric_card([old],'fat_kg','چربی','kg','amber')['latest'])
        self.assertEqual(_metric_card([old,record],'whr','نسبت کمر به باسن','','teal')['latest'],Decimal('0.91'))

    def test_bad_legacy_json_value_does_not_crash(self):
        bad=SimpleNamespace(measurements={'whr':'invalid','fat_kg':'NaN'})
        self.assertIsNone(scan_value(bad,'whr'))
        self.assertIsNone(scan_value(bad,'fat_kg'))
