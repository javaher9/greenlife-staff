# GreenLife Staff v6 — Finance / CRM integration

## What was added
- FinancialTransaction local cache so Staff dashboards stay fast and do not wait for CRM on every page load.
- Configurable CRM REST pull connector using environment variables; no CRM secret is committed to source.
- Idempotent sync by CRM external transaction ID.
- Persian/Jalali financial dashboard at `/finance/`.
- Revenue by branch and payment method.
- Secure management API at `/api/management/finance/summary/?date=1405/05/24` using the existing `X-Staff-API-Key` mechanism.
- Natural management query support for questions containing درآمد / فروش / مالی, including branch names.
- CLI sync: `python manage.py sync_crm_finance`.
- Sync log for troubleshooting.

## Server deployment
1. Set CRM variables in `.env` after Mr. Yavari provides the exact CRM API endpoint/token/schema.
2. `python manage.py migrate`
3. Test once: `python manage.py sync_crm_finance`
4. Open `/finance/` and verify totals against CRM.
5. For automatic refresh, run `python manage.py sync_crm_finance` from cron every 5–15 minutes (or adapt to the CRM webhook if available).

## Important
The connector is deliberately configurable because the exact private CRM API contract/token was not supplied in the source package. The default `/api/revenues/` and JSON field names are placeholders and MUST be aligned with the real API before first production sync.

## Example management questions after data sync
- درآمد امروز چقدر بود؟
- درآمد نیاوران امروز چقدر بود؟
- درآمد دیروز چقدر بود؟
- امروز چه کسی دیر آمد؟

All displayed dates remain Jalali; database timestamps remain timezone-aware Gregorian internally, which is the correct storage model.
