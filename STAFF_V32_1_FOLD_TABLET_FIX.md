# GreenLife Staff v32.1 — Fold / Tablet Fix

علت اصلی:
نسخه‌های PWA قبلی تمام viewportهای <=900px را Mobile در نظر می‌گرفتند.
Samsung Fold بازشده و بسیاری از Tabletها در همین بازه CSS width قرار می‌گیرند،
در نتیجه Sidebar موبایلی با Layout تبلتی ترکیب می‌شد.

اصلاحات:
- Bottom navigation فقط تا 639px.
- از 640px تا 1100px Sidebar تبلتی/دسکتاپ حفظ می‌شود.
- Layout داشبورد مدیریت روی Fold/Tablet پهن‌تر باقی می‌ماند.
- body class صریح برای dashboard به جای اتکای اصلی به :has().
- viewport-fit=cover.
- CSS واقعی cache-busted با ?v=v32.1.
- Service Worker cache version به v32.1 افزایش یافت.
- بدون Migration و بدون تغییر دیتابیس.

Deploy امن:
./deploy/safe_deploy.sh
