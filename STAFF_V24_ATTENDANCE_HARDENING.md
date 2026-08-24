# GreenLife Staff v24 — Attendance Security Hardening

این نسخه با هدف محکم‌کردن حضور و غیاب ساخته شده و ساختار دیتابیس را تغییر نمی‌دهد.

لایه‌های موجود و تأییدشده:
- زمان ورود و خروج فقط از زمان Server ثبت می‌شود.
- Geofence شعبه بر اساس Latitude / Longitude / Radius.
- کنترل Accuracy GPS؛ بالاتر از 200 متر رد می‌شود.
- اعتبارسنجی Lat/Lon و رد مختصات نامعتبر.
- ورود و خروج هر دو، در شعبه‌های Geofence-enabled، نیازمند موقعیت معتبر داخل محدوده هستند.
- تلاش ناموفق هیچ Attendance جعلی ایجاد نمی‌کند.
- فاصله و Accuracy ورود در Attendance ذخیره می‌شوند.
- GPS خروج و تلاش‌های ردشده در AuditLog ثبت می‌شوند.
- ثبت و اصلاح دستی مدیر با status=manual مشخص و در AuditLog با Before/After ثبت می‌شود.
- تلاش‌های خارج محدوده/کم‌دقت/نامعتبر برای مدیر قابل شمارش هستند.
- درخواست اصلاح حضور موجود حفظ شده است.

نکته:
برای فعال بودن Geofence باید در Django Admin > Branches برای هر شعبه Latitude/Longitude/Radius تنظیم و geofence_enabled روشن شود.

Migration لازم نیست.
