# GreenLife Staff v5 — Jalali + Smart Management Reporting

## Added
- Jalali/Shamsi dates across user-facing lists and forms.
- Native Jalali parser; no extra Python dependency is required.
- Branch work schedule: `work_start`, `work_end`, `grace_minutes`.
- Attendance lateness is calculated against each branch's schedule.
- Management analytics dashboard at `/analytics/`.
- Natural Persian management questions in the dashboard, including:
  - `امروز چه کسی دیر آمد؟`
  - `هاشمی کی آمد؟`
  - `امروز چه کسی نیامد؟`
  - `رتبه امتیازها`
- KPI records and scoring at `/kpi/`.
- Gamification score events; on-time check-in automatically awards 5 points once per day.
- Visual attendance bars and 30-day leaderboard.

## Read-only management API
For ChatGPT/integrations after final server connection:
- `GET /api/management/attendance/summary/?date=1405/05/24`
- `GET /api/management/query/?q=امروز چه کسی دیر آمد؟`

Authentication options:
1. Logged-in admin/manager session, OR
2. Header `X-Staff-API-Key` matching environment variable `STAFF_REPORT_API_KEY`.

Generate a long random API key on the production server. Do not put the real key in git/ZIP.

## Deploy
```bash
python manage.py migrate
python manage.py collectstatic --noinput
```
Then restart the Django/Gunicorn containers/services.

## Branch schedule
After deploy, set each branch's work start/end and grace period in Django admin. Defaults are 09:00–17:00 with 15 minutes grace.

## Notes
The database continues to store Gregorian dates (recommended and compatible with Django/PostgreSQL). The application displays and accepts Jalali dates in the UI. This avoids breaking database queries while making all staff-facing dates Shamsi.
