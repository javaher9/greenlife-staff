# GreenLife Staff v17 — Camp Module

## بخش‌های Camp
1. Dashboard
2. Purchase Requests
3. Inventory
4. Workers
5. Daily Tasks
6. Projects
7. Food Plan
8. Daily Photos
9. Reports
10. Camp Commander

## منطق اجرایی مهم
- همه تاریخ‌های فرم‌ها شمسی؛ ذخیره داخلی استاندارد Django.
- همه مبالغ در UI به تومان.
- خرید بالاتر از `owner_approval_threshold` فقط توسط Owner قابل تأیید است.
- فاکتور بدون عکس و فاکتور بالاتر از برآورد در UI هشدار دارد.
- Inventory ورود/خروج واقعی و جلوگیری از منفی شدن موجودی دارد.
- موجودی Low/Critical روی Dashboard هشدار می‌دهد.
- حضور کارگر و دستمزد روزانه ثبت می‌شود.
- Project بودجه، هزینه واقعی، درصد پیشرفت، مانع و عکس قبل/حین/بعد دارد.
- پروژه Over Budget یا بدون پیشرفت چندروزه هشدار می‌دهد.
- Food Plan هزینه روزانه و هفتگی را کنترل می‌کند.
- Daily Photos deadline دارد و عدم ثبت عکس پس از deadline هشدار می‌دهد.
- Reports شامل Today Summary و هزینه روز/هفته/ماه است.
- Camp Commander شامل Morning Check و Night Check و Summary پایان روز است.
- تعداد کارگر حاضر با برنامه Morning Check مقایسه و در صورت اضافه بودن هشدار داده می‌شود.

## دسترسی‌ها
- Owner/Admin: کامل + Commander + تأیید خریدهای بزرگ
- Supervisor: عملیات Camp، خرید زیر سقف، نیرو، پروژه، Task، عکس
- Worker: فقط Task خودش و Daily Photos
- Finance: خرید/فاکتور، Inventory read، Reports

Staff Admin به صورت پیش‌فرض Owner است.
Staff Manager به صورت fallback Supervisor است.
Staff Employee به صورت fallback Worker است.
CampMembership می‌تواند این mapping را override کند.

## Mock / Local Data
بدون API قابل استفاده است و تمام داده‌ها در PostgreSQL محلی Staff ذخیره می‌شوند.
برای بارگذاری داده نمونه:
`python manage.py seed_camp_demo`
یا Owner از Camp Dashboard روی «بارگذاری داده نمونه» بزند.

## API readiness
`core/camp_types.py` قراردادهای TypedDict برای Dashboard، Purchase، Inventory،
Worker، Task و Project را تعریف می‌کند.
Endpoint اولیه:
`/camp/api/summary/`

## Deploy
1. `python manage.py migrate`
2. `python manage.py collectstatic --noinput`
3. restart application
4. اختیاری: `python manage.py seed_camp_demo`

Migration جدید:
`0010_camp_module.py`
