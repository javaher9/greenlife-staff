# Green Life Telegram Agent v1

این Agent مستقیماً به مدل لیدهای Green Life Staff متصل است و سرویس جداگانه یا دیتابیس دوم ایجاد نمی‌کند.

## رفتار نسخه اول

- `/start` کاربر را برای ارسال شماره موبایل راهنمایی می‌کند.
- Contact یا شماره تایپی معتبر یک `ReferralLead` واقعی می‌سازد.
- لید در گروه `تلگرام - لینک` به اپراتور فعال کال‌سنتر تخصیص داده می‌شود.
- کاربر موضوع درخواست را با دکمه‌های Inline انتخاب می‌کند و روی همان لید ثبت می‌شود.
- پیام‌های بعدی کاربر به Notes همان لید افزوده می‌شود تا کارشناس انسانی ببیند.
- Agent تشخیص یا توصیه درمانی پزشکی خودکار ارائه نمی‌کند.
- webhook با `X-Telegram-Bot-Api-Secret-Token` محافظت می‌شود.

## متغیرهای محیطی

مقادیر واقعی فقط روی سرور در `.env` قرار بگیرند:

```env
TELEGRAM_BOT_TOKEN=<BotFather token>
TELEGRAM_WEBHOOK_SECRET=<long-random-secret>
TELEGRAM_WEBHOOK_URL=https://<public-host>/telegram/webhook/
TELEGRAM_SERVICE_OPTIONS=لاغری|مشاوره لاغری|دستگاه‌های لاغری|سایر
```

`TELEGRAM_WEBHOOK_URL` باید از اینترنت با HTTPS معتبر در دسترس Telegram باشد.

## ثبت webhook

بعد از Deploy و تنظیم env:

```bash
python manage.py set_telegram_webhook
```

یا برای مشخص کردن URL در همان فرمان:

```bash
python manage.py set_telegram_webhook --url https://<public-host>/telegram/webhook/
```

برای حذف webhook:

```bash
python manage.py set_telegram_webhook --delete
```

## تست

```bash
python manage.py test core.tests.test_telegram_lead core.tests.test_telegram_agent --verbosity 2
```

## مسیرها

- فرم عمومی تلگرام: `/telegram/`
- Telegram Bot webhook: `/telegram/webhook/`

## نکات امنیتی

- Token و Secret واقعی هرگز Commit نشوند.
- Secret طولانی و تصادفی باشد.
- webhook بدون `TELEGRAM_WEBHOOK_SECRET` عمداً با وضعیت 503 غیرفعال می‌ماند.
- فقط Contact متعلق به همان Telegram user پذیرفته می‌شود؛ Contact شخص دیگر برای ساخت لید رد می‌شود.
