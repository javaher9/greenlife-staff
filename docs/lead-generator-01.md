# Lead Generator 01 — GreenLife

Status: implementation specification, not deployed.

## Goal
Integrate lead acquisition and lead-source performance into the existing GreenLife app without replacing the operational call-center workflow. Starting target: >=50 qualified new leads/day (configurable, not an assertion of current performance).

## Core workflow
1. Capture a voluntarily submitted lead through website, landing page, campaign, authorized integration, or manual entry.
2. Store timestamp, source, campaign ID, center, contact permission and consent timestamp (if applicable); normalize Iranian mobile numbers.
3. Deduplicate by normalized mobile number; on an existing contact, append a source event rather than blindly creating another lead.
4. Validate fields; assign the lead using the **existing** call-center round-robin assignment service, never a duplicate distribution algorithm. Existing agents: Narges, Banafshah, Yasaman, Khorshidi. Respect existing Friday and carryover rules.
5. Track progress from created -> assigned -> contacted -> appointment -> attended -> purchased; record timestamps and owner.
6. Aggregate by source/campaign: captured, unique, qualified, contact rate, booked, attended, purchased, costs (if entered), cost per lead and conversion.

## UI — Lead Generator 01
- KPI-style glass visual language consistent with existing admin interface.
- Cards: leads today, qualified leads, source share, follow-up SLA violations, bookings, purchases.
- Filters: date range, campaign, source, active center, agent, status.
- Click-through from metrics to the corresponding filtered lead list and audit trail.
- Alerts: pace below daily target; lead not contacted within defined SLA; source integration failure; lead registration stopped for >2 hours during 08:00-24:00 (distinguish manual Instagram-direct capture from API integrations).
- Do not show closed Urmia center; keep Istanbul out of the initial reporting scope unless enabled explicitly.

## Integration contracts to implement after inspecting actual code
- POST /api/lead-generator/leads: accepts name(optional), phone(required), source(required), campaign_id(optional), consent, submitted_at; authenticated integration only, idempotency key recommended.
- GET /api/lead-generator/summary with filters; role-based access.
- GET /api/lead-generator/alerts and acknowledgement endpoint.
- Reuse existing lead models / access controls / call center allocator / logging and current SMS infrastructure. Do not invent a second CRM.
- Protect personal data; do not scrape private profile phone numbers or send unsolicited marketing without permission.

## Acceptance criteria
- Same inbound contact submitted twice yields one canonical lead and multiple attribution events, according to existing app rules.
- New qualified leads enter the current allocator and are visible to agents.
- Existing manual direct registration remains functional and distinct from Instagram-direct registration.
- No unintentional SMS sends; integrations disabled by default until tested.
- Automated tests cover duplicate handling, permissions, day-based allocation, and alerts.
- Feature flag and migration/backout plan required before production activation; do not deploy to production based on this document alone.
