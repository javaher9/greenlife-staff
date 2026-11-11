# Internal manager operations: implementation and rollout

Executive DARK dashboard at `/live/`, reached by `/` for `internal_manager`.
Branch starts from `27e05a32140c357dc00661067c23b2adefd9d4d9`.

## Implemented

- Existing monthly target engine/policy boundaries projected to name, qualitative
  level/status/action only. No plan, value, percentage or numeric breakdown reaches
  the internal-manager template context, `/sales-targets/` or `/api/live/`.
  No receipt for a configured subject is explicitly unknown, not green/zero.
  Monthly status is never presented as a daily failure. Existing admin page remains.
- Existing compact lead archive, scoped filters and restricted supervisory detail;
  no phone search, free-text notes, contact links or exports. Old referral/lead
  mutation, detail, patient and export routes are closed for this role. Names are
  sanitized too. New call-result audit timestamps are explicit; unknown historical
  action time stays unknown. `updated_at` is not a call timestamp.
- One conditional/locked leave transition used by quick and full-page review;
  country/personnel scope, self-review prohibited, rejection note required,
  append-only AuditLog timestamp and StaffNotification in the same transaction.
  List pagination and separate pending-leave plaque. Quick UI goes to full review
  so reason and date overlaps can be read before deciding.
- Shared alerts retain pending AND contacted customer requests. Customer queue and
  mutations use the same country/role/branch queryset. Reading an alert changes
  nothing. Tasks disappear only when their underlying state changes.
- Manual DM event tracking on **instagram_manual_lead** and authorized operator
  quick-entry only. The unrelated call_center_direct_lead_create is NOT a manual
  Instagram event. Existing exact source routes provide legacy evidence; neither
  group membership nor mutable notes/update time is used.
- Tehran clock: [08:00, midnight), origin max(08:00, actual registration), strict
  >2 hours. New non-destructive OperationsIncident table with unique gap key and
  real-event resolution. History survives midnight. Existing self-hosted production
  Actions pattern schedules a dedicated no-message monitoring command every 10m.
  GitHub schedules are best-effort, not a real-time SLA. Verify first successful
  scheduler invocation after deployment; no claims of live scheduling before then.
  Existing MarketingWorkerState stores a separate scheduler heartbeat; missing or
  stale heartbeat is explicitly displayed. Monitoring uses the actual Iran intake
  flow; no synthetic per-country Instagram workflow is assumed for other countries.
- Collapsible attendance records, approved today/tomorrow leave, current stored
  visitor stages, open equipment/internal issues and overdue tasks.

## Explicitly incomplete / do not represent as completed

- Validated daily acquisition goals (50 total call-center leads, 10 network leads,
  5 genuine network members): existing records lack reliable test/import/new-member
  provenance. The old incorrect `all ReferralLead.count()` progress is removed.
  UI says insufficient data; it does NOT claim target success or failure. No daily
  missed-acquisition history is manufactured. Constants above are requirements,
  not an implemented numerical acquisition engine.
- Source ownership and enrollment provenance must be added at each existing intake
  before these metrics can safely be enabled. Staff auto-profiles must be excluded.
  Existing monthly staff-network report is a raw record-count report, NOT these goals.
- Hourly leave has no start/end-time fields. Review explicitly says unavailable.
  Date overlap is not shift coverage. No fabricated same-shift conflict/coverage.
- Staffing deficits, pre-shift readiness aggregation and missed-report synthesis
  are not implemented. Existing checklist page is linked; no parallel checklist.
- Current visit model has only doctor/consultant/payment/closed stages, not timestamps
  for all required phases. Intake/scan stage reconciliation, SLA configuration and
  stalled-visit timing remain to implement. No fake durations or critical thresholds.
- DeviceIssue currently has new/reviewing/resolved; InternalRequest open/doing/done/
  rejected. Assignment/independent closure confirmation and QC recheck state machine
  remain to implement. Existing resolution actions have not been reinterpreted as
  an independent verification.
- Training receipt/read/execution, recruitment/probation summaries and editable
  end-of-day briefing are not included in this first implementation.
- This change is not a claim that all pre-existing app endpoints have passed a
  complete country/role security audit. Only touched/new paths have focused tests.

## Deployment / rollback

Do not use Railway or change hosting. Existing `.github/workflows/deploy.yml` uses
`self-hosted, linux, greenlife-prod` and the existing safe deployment script.
Only merge after functional tests, PostgreSQL concurrency and responsive browser
checks pass. Compare deployed SHA and verify the internal-manager page read-only
before reporting live success. Never approve real leave or move real leads to test.

`INTERNAL_MANAGER_OPERATIONS_ENABLED=0` restores the previous `/live/` page, while
privacy boundaries remain enforced. A code rollback should leave the new incident
table intact; no reverse migration/data deletion is needed. Old code ignores it.
Disable the dedicated monitoring workflow if rolling back the command. Use existing
safe deploy/rollback mechanism, never `docker compose down`.

## Tests

Focused suite: internal_manager_operations, internal_manager_role, all_leads,
sales_targets_dashboard, customer_portal. Includes actual response/context checks,
permission bypass attempts, CSRF mutation blocking, exact target thresholds, leave
note/double-decision behavior, Tehran boundaries and durable incident dedup.
PostgreSQL-only TransactionTestCase exercises two competing leave decisions.
Opt-in StaticLiveServer browser test uses synthetic users and checks 390/820/1440px.
Local Chromium startup is blocked by the executor's socket policy; CI browser test
is provided instead. Until that check succeeds, visual verification is incomplete.

## Observed verification (2026-11-11)

- Local focused regression suite: 52 tests, 51 passed, PostgreSQL-only concurrency
  skipped. The corresponding PostgreSQL CI suite passed, including concurrency.
- Full local core suite: 633 tests, 26 failures, 39 errors, 2 skipped. Baseline
  `27e05a3` in a separate untouched worktree: 617 tests, 28 failures, 39 errors.
  Final comparison found no new failing test names versus baseline. This does NOT
  mean the entire suite is green; baseline defects/dependency differences remain.
- Current GitHub PR is #370. No merge or live deployment claimed.
