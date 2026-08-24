# GreenLife Staff v18.4 — Attendance Geofence

- ثبت ورود پرسنل می‌تواند برای هر شعبه به GPS محدود شود.
- Latitude/Longitude و شعاع مجاز در Branch تنظیم می‌شود.
- اگر Geofence فعال باشد، بدون Location ورود ثبت نمی‌شود.
- GPS با دقت بدتر از ۲۰۰ متر رد می‌شود.
- فاصله واقعی از شعبه در Backend با Haversine محاسبه می‌شود.
- مختصات، دقت GPS، فاصله و وضعیت تأیید در Attendance Audit ذخیره می‌شود.
- ورود خارج محدوده رد می‌شود.
- ثبت دستی مدیر همچنان از مسیر مدیریتی مستقل قابل انجام است.
- Geofence به‌صورت پیش‌فرض خاموش است تا قبل از واردکردن مختصات شعبه، حضور و غیاب فعلی خراب نشود.

راه‌اندازی:
1. python manage.py migrate
2. Django Admin > Branches > شعبه
3. latitude / longitude مرکز شعبه را وارد کنید.
4. attendance_radius_m را مثلاً 100 یا 150 بگذارید.
5. geofence_enabled را روشن کنید.
6. collectstatic و rebuild/restart.

نکته امنیتی: GPS مرورگر ضدجعل مطلق نیست. این نسخه جلوی ثبت ساده از منزل/مسیر را می‌گیرد، اما برای امنیت بالاتر می‌توان Device binding / Wi‑Fi / QR rotating / native anti-spoof را بعداً اضافه کرد.
