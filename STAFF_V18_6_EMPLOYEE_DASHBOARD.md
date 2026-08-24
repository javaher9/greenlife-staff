# GreenLife Staff v18.6 — Employee Dashboard Cleanup

تغییر اصلی:
- بخش «مرکز عملیات مجموعه / GREENLIFE OPERATIONS» برای Role = employee مخفی شد.
- کارمند عادی همچنان این بخش‌های روزانه را می‌بیند:
  - ثبت گزارش امروز
  - چک‌لیست امروز
  - وضعیت وظایف
  - هشدار گزارش روزانه
  - اعلان‌ها
  - حضور امروز
  - وظایف امروز
- مدیر شعبه و مدیر سیستم همچنان مرکز عملیات مجموعه را می‌بینند.
- هیچ تغییری در Backend، Database، Voice، Geofence یا Shift Groups ایجاد نشده است.

Deploy:
- Migration لازم نیست.
- در صورت استفاده از Docker: rebuild/restart کافی است.
- در صورت cache شدن template/static، سرویس Web را restart کنید.
