# GreenLife Staff v18.2 — Voice/Report Duplicate Guard

اصلاحات:
- جلوگیری از ثبت دوباره یک Report در Retry یا Double Tap
- submission_id یکتا در هر فرم
- idempotency check در Backend
- قفل دکمه ارسال برای گزارش متنی، فایل آپلودی و Voice
- حفظ Voice Fix و AI JSON Fix نسخه‌های قبلی
- ابزار Audit برای بررسی Duplicateهای موجود

Deploy:
python manage.py migrate
python manage.py collectstatic --noinput
docker compose up -d --build

Audit اختیاری:
python manage.py report_duplicate_audit
