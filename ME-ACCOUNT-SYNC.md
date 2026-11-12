# Verified member account bridge

The existing customer SMS login and database identity back GreenLife Me. No new provider credentials or parallel phone directory. App browser uses same-origin Vercel rewrites for `/customer/*` and `/static/*`; Django CSRF remains enforced, and only the canonical app origin is added to trusted origins. Sessions remain HttpOnly server-backed sessions. No bearer keys enter localStorage.

New additive tables: account snapshot/version/consent, unique member/day reward ledger, metadata-only synchronization audit. Each write locks the member row and requires exact revision; stale devices receive 409. Identity is taken only from the verified customer session. Payloads and keys are bounded; optional local activity history is excluded. Previously granted awards persist through corrections; client-provided award balances are ignored. Only valid self-reports from the last seven Tehran calendar days can earn a daily award. These free app hearts do not authorize clinical sessions, monetary credit, paid content or staff access.

Guest data uploads only after the signed-in member confirms ownership and consent. Existing account data takes priority on another device; guest/local drafts are backed up locally. Conflict requires explicit reload of account version; no silent overwrite. Do not advertise successful cross-device SMS login until real OTP flow is observed. Automated two-session tests cover shared data, isolation, stale revision, grant uniqueness and CSRF.

These models are the member-management foundation. No public admin endpoint or new staff privilege is added. A future management page must apply staff role and branch/assignment permissions, distinguish self-reported compliance from verified attendance, and require channel consent and explicit approval for messages. Do not infer failure from absent reports.

Operational deployment: migrate the three additive tables via the existing safe deployment workflow before enabling the Vercel account adapter. Existing customer/clinic routes remain intact. Preserve database backups in the existing deployment process. SMS is sent only when a person submits the login form; no test OTP bypass exists in production.

References: https://docs.djangoproject.com/en/5.2/topics/http/sessions/ and https://vercel.com/docs/routing/rewrites
