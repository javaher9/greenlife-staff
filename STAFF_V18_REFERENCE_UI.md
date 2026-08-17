# GreenLife Staff v18 — Reference Premium UI

این نسخه بر پایه GreenLife Staff v17 + Camp + Voice FieldFile Fix ساخته شده است.

## تغییرات اصلی UI
- بازطراحی شِل اصلی اپ به سبک روشن و پریمیوم GreenLife
- انتقال Sidebar اصلی به سمت چپ مطابق تصویر مرجع
- Header سبک با Search، اطلاعات کاربر و Notification
- Camp Dashboard با ۶ KPI اصلی
- بخش هشدارهای مهم
- Quick Review
- نمودار هزینه ۷ روز اخیر
- آخرین فاکتورها
- موجودی‌های رو به اتمام
- پروژه‌های عقب‌افتاده
- Today Summary و Camp Commander
- Responsive برای موبایل و تبلت
- حفظ RTL، تاریخ شمسی و مبالغ تومان

## نکات مهم
- Voice FieldFile Fix نسخه قبلی حفظ شده است.
- منطق Camp و Migrationهای v17 حفظ شده‌اند.
- API و Endpointهای قبلی حذف نشده‌اند.
- پورت‌ها و تنظیمات deployment تغییر داده نشده‌اند.

## Deploy
python manage.py migrate
python manage.py collectstatic --noinput
سپس سرویس/کانتینر را rebuild/restart کنید.
