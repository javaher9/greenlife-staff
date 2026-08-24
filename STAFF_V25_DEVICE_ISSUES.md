# GreenLife Staff v25 — Device Issue Reporting

- دکمه «گزارش خرابی دستگاه» در پروفایل پرسنل
- فرم نام دستگاه + شرح خرابی
- صفحه «گزارش‌های من» برای مشاهده وضعیت
- ارسال Notification خودکار به:
  - admin
  - manager1
  - sadeghi
  - همه مدیران سیستم
  - مدیر شعبه همان پرسنل
- صفحه مدیریت خرابی‌ها برای Admin / Manager / username=sadeghi
- وضعیت‌ها: جدید / در حال بررسی / رفع شده
- یادداشت مدیر یا مسئول فنی
- اطلاع‌رسانی به پرسنل هنگام تغییر وضعیت
- خانم هاشمی بهتر است:
  Role = manager
  Job title = مدیر داخلی

Deploy:
python manage.py migrate
python manage.py collectstatic --noinput
restart/rebuild service
