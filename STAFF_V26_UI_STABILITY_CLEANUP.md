# GreenLife Staff v26 — UI System + Stability Cleanup

این نسخه عمداً فیچر سنگین جدید ندارد و برای یکدست‌کردن محصول و کاهش ریسک ساخته شده است.

## Stability
- Login نام کاربری Case-insensitive شد:
  Moradi / moradi / MORADI همگی username ذخیره‌شده را پیدا می‌کنند.
- بدون تغییر مدل‌ها و بدون Migration جدید.
- قابلیت‌های v25 و نسخه‌های قبلی حفظ شده‌اند.
- Python syntax validation و ZIP integrity تست شده‌اند.

## UI System
- Design Token سراسری برای رنگ، Border، Radius، Shadow و Focus.
- یکدست شدن Card / Panel / Hero.
- یکدست شدن Button و Ghost Button.
- یکدست شدن Input / Select / Textarea و Focus state.
- جدول‌های روشن‌تر، Header ثابت و Hover استاندارد.
- Badge و Statusهای یکپارچه.
- پیام‌های success/error/warning تمیزتر.
- Sidebar و Topbar روشن‌تر و حرفه‌ای‌تر.
- Active state بهتر برای منوهای اصلی.
- Responsive cleanup برای Tablet / Mobile.
- iOS input zoom prevention.
- هماهنگی UI صفحات:
  Dashboard، Profile، Attendance، Reports، Guidelines، Device Issues و Manager UI.

Deploy:
- Migration لازم نیست.
- collectstatic و restart/rebuild کافی است.
