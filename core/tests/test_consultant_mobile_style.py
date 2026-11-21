"""No-database checks for the consultant phone layout and light KPI contrast."""
from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase


class ConsultantMobileStyleTests(SimpleTestCase):
    def test_mobile_kpis_are_light_and_grid_can_shrink(self):
        template = Path(
            get_template('core/consultant_sales_outcomes.html').origin.name
        ).read_text(encoding='utf-8')
        # The media rule is intentionally one line with nested braces.
        css = next(line for line in template.splitlines()
                   if line.startswith('@media(max-width:700px){'))
        self.assertIn('grid-template-columns:minmax(0,1fr)!important', css)
        self.assertIn('.care-metric{background:#f5fbf7;border-color:#d7e9df}', css)
        self.assertIn('.care-metric small,.care-metric em{color:#516f66}', css)
        self.assertIn('.care-metric strong{color:#173f35}', css)
        self.assertNotIn('background:#1a3040', css)

    def test_mobile_and_tablet_areas_follow_the_single_column_layout(self):
        template = Path(
            get_template('core/consultant_sales_outcomes.html').origin.name
        ).read_text(encoding='utf-8')
        # At <=1050px the queue/workspace/rail become one column; areas must too.
        responsive_rule = next(
            line for line in template.splitlines()
            if line.startswith(
                'body.gl-app.gl-authenticated.gl-page-consultant_sales_outcomes '
                '.app-main .care .care-grid{grid-template-columns:minmax(0,1fr)!important'
            )
        )
        self.assertIn(
            'grid-template-areas:"queue" "workspace" "rail"!important',
            responsive_rule,
        )
