# GreenLife Staff v18.3 — Mobile Navigation Fix

اصلاح اصلی:
- رفع باگ ناپدید شدن آیتم‌های منو در موبایل‌های کوچک (خصوصاً iPhone)
- Bottom Navigation استاندارد با ۵ آیتم:
  - داشبورد
  - گزارش‌ها
  - Finance
  - Camp
  - بیشتر
- منوی «بیشتر» به شکل Bottom Sheet/Drawer اسکرول‌شونده
- نمایش همه مسیرهای مجاز:
  - پنل مدیریتی
  - پرسنل
  - حضور و غیاب
  - KPI
  - آموزش
  - درخواست‌ها
  - اعلان‌ها
  - پروفایل
  - خروج
- حفظ Role-based visibility برای گزینه‌های مدیریتی
- بدون تغییر در Backend، Database یا Portها
- تمام Fixهای Voice / AI JSON / Duplicate نسخه‌های قبل حفظ شده‌اند.

Deploy:
python manage.py collectstatic --noinput
docker compose up -d --build

Migration جدیدی برای این نسخه لازم نیست.
