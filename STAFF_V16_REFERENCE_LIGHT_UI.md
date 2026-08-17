# GreenLife Staff v16 — Reference Light Premium UI

بازطراحی بر اساس طرح تأییدشده:
- زمینه روشن سفید/طوسی با ته‌رنگ سبز بسیار ملایم
- Glassmorphism روشن و ظریف
- کارت‌های سفید با Shadow بسیار نرم
- GreenLife green فقط به عنوان Accent
- تایپوگرافی و کنتراست مدیریتی و تمیز
- CEO Score روشن با Ring سبز
- جداول، تقویم، فرم‌ها، کارت‌های Staff و Executive Today هماهنگ
- بدون Migration جدید نسبت به v14

Deploy:
python manage.py collectstatic --noinput
restart application
اگر migrationهای v14 هنوز نصب نشده‌اند: python manage.py migrate
