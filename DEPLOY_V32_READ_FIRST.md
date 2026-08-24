# GreenLife Staff v32.0 — Deploy Rules

## مهم‌ترین قانون دیتابیس
برای آپدیت، هرگز این دستورات را اجرا نکنید:
- `docker compose down -v`
- `docker volume rm ...`
- حذف دستی volume دیتابیس
- جایگزینی PostgreSQL volume با نام جدید بدون انتقال داده

## روش امن
در پوشه پروژه روی سرور:
```bash
./deploy/safe_deploy.sh
```

این اسکریپت قبل از آپدیت:
1. از PostgreSQL خارجی، با تنظیمات `.env`، بکاپ می‌گیرد.
2. اگر بکاپ خالی باشد Deploy را متوقف می‌کند.
3. Image را Build و سرویس‌ها را بدون حذف Volume جایگزین می‌کند.
4. Migration، راه‌اندازی سرویس و Healthcheck را اجرا می‌کند.

در CI/CD، همین فرایند به‌طور خودکار از طریق `scripts/deploy_runner.sh` اجرا می‌شود.

## نسخه
تمام صفحات پایین خود نسخه `v32.0` را نمایش می‌دهند.

## Cache
Static assets دارای query-string نسخه هستند و Service Worker نیز برای هر نسخه Cache جدید می‌گیرد.
صفحات پویا و اطلاعات پرسنل Cache آفلاین نمی‌شوند.
