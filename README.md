# GreenLife Staff v2

نسخه اصلاح‌شده برای استقرار Docker روی سرور GreenLife.

## اصلاح اصلی v2

Migration اولیه اپ `core` داخل بسته قرار گرفته است؛ بنابراین جدول‌های `core_branch`، پروفایل پرسنل، وظایف، اطلاعیه‌ها و گزارش‌های روزانه پیش از Seed شدن ساخته می‌شوند.

## نصب

1. فایل را Extract کنید.
2. `.env.example` را به `.env` کپی کنید و مقادیر واقعی را وارد کنید.
3. مطمئن شوید PostgreSQL از داخل کانتینر روی `POSTGRES_HOST:POSTGRES_PORT` قابل دسترسی است.
4. اجرا:

```bash
docker compose down
docker compose build --no-cache
docker compose up -d
```

5. بررسی:

```bash
docker compose ps
docker compose logs -f web
```

خروجی Nginx به‌صورت پیش‌فرض روی پورت `8085` منتشر می‌شود و از طریق `NGINX_PORT` قابل تغییر است.

## نکته درباره دیتابیس قبلی

این نسخه از PostgreSQL نصب‌شده روی سرور استفاده می‌کند و کانتینر دیتابیس جدا ایجاد نمی‌کند. اگر از اجرای قبلی Volume بلااستفاده باقی مانده، حذف آن الزامی نیست؛ اما کانتینرهای قبلی پروژه باید قبل از اجرای نسخه جدید متوقف شوند.

## AI

بدون `OPENAI_API_KEY` ثبت متن و وویس کار می‌کند، اما تبدیل صوت و تحلیل هوشمند غیرفعال می‌ماند.

## امنیت

- رمز ادمین اولیه را بلافاصله تغییر دهید.
- `SECRET_KEY` طولانی و تصادفی باشد.
- فایل `.env` وارد Git نشود.
- دسترسی PostgreSQL فقط برای IP/شبکه مورد نیاز باز باشد.

## اتصال فقط‌خواندنی MCP برای ChatGPT

این نسخه یک endpoint استاندارد و بدون Session برای گزارش‌های مدیریتی دارد:

```text
https://report.greenlifeclinics.com/mcp/
```

احراز هویت با یکی از هدرهای زیر انجام می‌شود. مقدار کلید فقط در `.env` سرور
نگهداری می‌شود و نباید داخل Git قرار گیرد:

```text
Authorization: Bearer <MCP_API_KEY-or-STAFF_REPORT_API_KEY>
X-Staff-API-Key: <MCP_API_KEY-or-STAFF_REPORT_API_KEY>
```

ابزارهای منتشرشده فقط‌خواندنی هستند:

- `get_attendance_summary`: خلاصه حضور، تأخیر و افراد بدون ورود برای یک تاریخ
- `ask_management`: پرسش مدیریتی فارسی درباره داده‌های ثبت‌شده Staff

اگر `MCP_API_KEY` خالی باشد، endpoint از `STAFF_REPORT_API_KEY` استفاده می‌کند.
اگر هر دو خالی باشند، سرویس با وضعیت `503` غیرفعال می‌ماند.


## Temporary local-IP CSRF bypass
For local testing at `http://192.168.40.96:8085`, set these values in `.env`:

```env
DISABLE_CSRF=1
CSRF_COOKIE_SECURE=0
SESSION_COOKIE_SECURE=0
```

Then rebuild/restart:

```bash
docker compose down
docker compose up -d --build
```

Before production or enabling HTTPS/subdomains, restore `DISABLE_CSRF=0`.
