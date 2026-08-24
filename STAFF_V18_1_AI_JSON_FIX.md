# GreenLife Staff v18.1 — AI JSON Processing Fix

اصلاحات:
- حفظ Voice FieldFile fix
- جلوگیری از خطای `Expecting value: line 1 column 1`
- تشخیص پاسخ خالی OpenAI
- حذف Markdown code fences از JSON
- استخراج JSON object از پاسخ‌های دارای متن اضافه
- پیام خطای فارسی و قابل فهم در صورت JSON نامعتبر
- نرمال‌سازی `tags`
- حفظ گزارش و Voice در صورت خطا برای Retry

بعد از Deploy:
1. `OPENAI_API_KEY` داخل کانتینر/Environment واقعاً مقدار داشته باشد.
2. `OPENAI_ANALYSIS_MODEL` و `OPENAI_TRANSCRIBE_MODEL` بررسی شوند.
3. کانتینر rebuild/restart شود.
4. روی همان گزارش دوباره «پردازش با AI» زده شود.
