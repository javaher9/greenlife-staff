# GreenLife Staff v4 — Attendance

این نسخه روی `greenlife_staff_v3_cicd_ready` ساخته شده و Voice Fix قبلی را حفظ می‌کند.

## قابلیت‌های اضافه‌شده
- ثبت ورود روزانه توسط کارمند
- ثبت خروج روزانه
- تشخیص اولیه تأخیر بعد از ساعت 09:15
- تاریخچه 31 روز اخیر هر کارمند
- محاسبه مدت کارکرد بین ورود و خروج
- صفحه گزارش تیم برای Manager/Admin
- فیلتر گزارش براساس تاریخ
- نمایش افراد بدون ثبت ورود، تأخیرها و تعداد حاضرها
- ثبت دستی و اصلاح رکورد توسط Manager/Admin
- محدودیت مدیر شعبه فقط به پرسنل شعبه خودش
- نمایش وضعیت حضور در Dashboard
- API خواندنی وضعیت امروز: `/api/attendance/today/`
- Admin registration
- Migration: `core/migrations/0003_attendance.py`

## Deploy
از روند فعلی پروژه استفاده شود. مهم است migration اجرا شود:

`python manage.py migrate`

یا با Docker/اسکریپت deploy موجود پروژه.

## نکته ساعت کاری
در نسخه فعلی، ورود بعد از `09:15` به صورت اولیه Late ثبت می‌شود. اگر ساعات کاری شعب متفاوت است، در نسخه بعدی Shift/Schedule به Branch یا Employee اضافه شود.
