# GreenLife Staff v31 — PWA App Mode

هدف:
GreenLife Staff به جای حس «لینک وب»، روی موبایل/Fold/Tablet مثل اپ واقعی نصب و اجرا شود.

ویژگی‌ها:
- Web App Manifest
- آیکون 192 و 512
- Display: standalone
- Theme color GreenLife
- Service Worker با Network-first برای صفحات پویا
- Cache فقط برای Static assets، تا اطلاعات پرسنل stale نشود
- دکمه Install App در Android/Chrome
- راهنمای Add to Home Screen در iPhone/iPad Safari
- Bottom navigation ثابت برای موبایل/Fold
- Safe-area support
- حذف حس Browser navigation تا حد ممکن پس از نصب

نکته:
برای PWA کامل، سایت باید روی HTTPS باشد.
Migration لازم نیست.
