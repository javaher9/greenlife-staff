# Green Life Staff — UI implementation rules (EXECUTIVE)

These rules are mandatory for all future UI design, implementation, review, and visual QA. They supersede any blanket "Dark Premium for all Staff" statement in older version notes.

## Theme by context, not merely screen size
- **Staff operational desktop/workstation pages:** LIGHT theme. Examples: call center, secretary/reception, consultant, doctor, and other daily desk workflows.
- **Executive/owner/management pages:** DARK premium theme by default, unless that screen is explicitly specified otherwise.
- **Staff PERSONAL mobile pages:** DARK premium theme. Examples: individual attendance/check-in/out, personal profile and personal tools.
- **Do not infer that all mobile pages must be dark or all desktop pages must be light.** Screen PURPOSE and ROLE take precedence. A responsive operational staff page does not automatically become dark just because it is opened on a phone; personal staff mobile pages are dark.
- When classification is unclear, identify the page's primary role/purpose from existing routes and established patterns before implementing. Do not change any existing page's theme solely based on a viewport breakpoint.

## Visual reference
- Treat the existing KPI page's layout discipline, spacing, button consistency, card structure, typography and color semantics as the **reference for shared design patterns**. Inspect its real templates/styles/components before creating a new design; do not approximate from memory.
- Reuse existing design tokens and shared components. Create or consolidate shared components if justified; avoid one-off CSS that silently changes button sizes, colors or fonts.
- Apply the **correct LIGHT or DARK variant** to each page rather than copying the KPI page's background/theme indiscriminately.
- Use RTL-appropriate alignment, readable Persian text, consistent avatars and English digits where the relevant workflow already uses them.

## Required checks before claiming work complete
1. Identify page role/purpose and record expected theme (light operational / dark executive / dark personal mobile).
2. Inspect KPI reference and equivalent existing page/component; reuse established colors, buttons, spacing, font and cards.
3. Validate the working page visually at desktop and mobile/tablet widths, and compare it against the appropriate reference. Check no accidental dark blocks on operational LIGHT screens.
4. Verify critical actions and permissions with functional tests where available.
5. Report separately: code committed, tests run/passed, deploy workflow status, and **live deployed version verified or unverified**. Never equate a GitHub commit with a successful live deployment.

## Notes
The project may contain older design documents (e.g. STAFF_V12_PREMIUM_UI_SYSTEM.md) describing an all-dark premium design. The owner clarified the three-context theme split on 2026-10-11; follow these rules over older blanket theme recommendations. Existing page-specific explicit design instructions still apply.
