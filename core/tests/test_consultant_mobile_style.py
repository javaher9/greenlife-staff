"""No-database checks for the consultant phone layout and light KPI contrast."""
from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


class ConsultantMobileStyleTests(SimpleTestCase):
    def test_mobile_kpis_are_light_and_grid_can_shrink(self):
        template = Path(
            get_template('core/consultant_sales_outcomes.html').origin.name
        ).read_text(encoding='utf-8')
        start = template.index('@media(max-width:700px){')
        end = template.index('}', start) + 1
        css = template[start:end]
        self.assertIn('grid-template-columns:minmax(0,1fr)!important', css)
        self.assertIn('.care-metric{background:#f5fbf7;border-color:#d7e9df}', css)
        self.assertIn('.care-metric small,.care-metric em{color:#516f66}', css)
        self.assertIn('.care-metric strong{color:#173f35}', css)
        self.assertNotIn('background:#1a3040', css)
