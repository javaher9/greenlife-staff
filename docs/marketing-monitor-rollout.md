# Marketing monitor rollout — no-downtime safety gate

This first worker is **a read-only CRM intake monitor**, NOT a discovery, Instagram or lead-generation robot. It never contacts prospects, sends SMS, or creates/modifies ReferralLead entries. It scans daily lead counts in Iran at a fixed interval and writes only a tiny heartbeat row.

## Safe release prerequisites
1. Resolve unrelated legacy CI failures or explicitly review identical baseline failures. Do not silently disable quality gates.
2. Confirm the approved deployment is blue-green, backs up first, runs an additive CreateModel migration and health-checks the candidate before cutover.
3. Deploy with `MARKETING_MONITOR_ENABLED` absent or `0` (off by default), then verify normal call-center workflow and availability.
4. Set `MARKETING_MONITOR_ENABLED=1` **only on the private server .env** as a separate, explicit activation; run the deploy workflow to start the process. Do not store credentials in Git.
5. Verify only one worker container is running and the Command Center `Lead Commander` card reports a recent heartbeat. API responses contain counts and timestamps only, no patient PII.
6. If CPU/DB/response time/lead routing changes, set the flag back to `0` and redeploy/stop the monitor container; existing lead processing stays independent.

Worker runs `python manage.py run_marketing_monitor --loop --interval 60`. Freshness expires after 180s. Public API must not claim that external lead acquisition is active.

## Phase two (not activated by this change)
Connect consent-based `greenlifeclinics.com` lead forms to the existing authenticated `/api/integrations/leads/` endpoint, verify true round-robin & branch attribution, then separately implement external-source agents with supported APIs and explicit rate limits.
