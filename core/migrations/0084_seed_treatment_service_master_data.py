"""Seed shared catalog titles from the legacy CRM, without inventing item details.

Uses the existing TreatmentCatalogItem table, with branch=NULL for reuse in
all branches. Safe to rerun; never overwrites an existing title's metadata.
"""
from django.db import migrations

CATALOG_ITEMS = {
    "diet": (
        "Keto-Fast",
        "Saf-150 مزاج گرم و خشک",
        "Dam-160",
        "Dam-150 گرم و تر",
        "Bal-160",
        "Bal-150",
        "Sod-160",
        "Sod-150",
        "Sib-150",
        "Cof-150",
        "Asl-150",
        "Raw-150",
        "Z-150",
        "W-150",
        "شوک بعد تثبیت",
        "رژیم ِیک هفتگی شوک",
        "Por-150",
        "O-150",
        "E-150",
        "Dar-150",
        "I-150",
        "Sabz-150",
        "Gol-150",
        "Mush-150",
        "Egg-150",
        "L-150",
        "C-180",
        "C-150",
        "Miv-180",
        "K-150",
        "Aloo-150",
        "F-150",
        "C-F-150",
        "D-150",
        "A-180",
        "B-180",
        "B-150",
        "P-150",
        "Liquid-150",
        "Alkaline-150",
        "Japan-150",
        "Super Soup-150",
        "A-150",
        "R-50",
        "R-150",
        "R-250",
    ),
    "recommendation": (
        "نکات طلائی در لاغری",
        "توضیح سالاد گرین لایف",
        "آیا میدانید قسمت چهارم",
        "آیا میدانید قسمت سوم",
        "آیا میدانید قسمت دوم",
        "آیا میدانید؟ قسمت اول",
        "چاقی یعنی مرض",
        "غذای سالم و ناسالم 2",
        "غذای سالم و ناسالم 1",
        "بخورید تا زودتر بمیرید",
        "100 نکته ناب سلامتی",
        "40 نکته مهم  لاغری",
        "خسته نشوید",
        "سخن بزرگان در مورد اراده و پشتکار  قسمت 5 و 6",
        "سخن بزرگان در مورد اراده و پشتکار قسمت 3 و 4   Will2",
        "سخن بزرگان 1 Will1",
        "توصیه های شیردهی",
        "جدول کالری ها 1",
        "اثر گرما زائی غذا TEF",
        "ترک اعتیاد",
        "بخورید تا زودتر بمیرید 2",
        "انسولین 4",
        "انسولین 3",
        "انسولین 2",
        "انسولین 1",
        "هشدار دوباره به شما",
        "هشدار برای شما",
        "قدرتی بالاتر از اراده 4",
        "قدرتی بالاتر از اراده 3",
        "قدرتی بالاتر از اراده 2",
        "قدرتی بالاتر از اراده 1",
        "مبارزه با چاقی",
        "هر چه فکر کنید همان میشود",
        "دو راه کم کردن اشتها",
        "آماده باشید",
        "عوض شو یا بمیر",
        "یبوست 3",
        "یبوست 4",
        "یبوست  2",
        "یبوست 1",
        "تثبیت ماه اول",
        "کلید لاغری",
        "توصیه ها در ماه مبارک رمضان",
        "دستورات روزه در ایام غیر ماه رمضان",
        "برنامه در اولین مراجعه",
        "تاب آوری",
        "رمز لاغری",
        "توصیه های دیابت",
    ),
    "print_template": (
        "عنوان نسخه",
        "نسخه دستی",
        "نیاز ندارد",
        "chitosan",
        "Fluoxetin 30",
        "Xeno",
        "Tag 30",
        "Tag 15",
        "Slim Quick",
        "Cap Zinc",
        "L-Active",
        "Senso",
        "Obestop",
        "Algo",
        "Cumin",
        "Vin",
        "Tea",
        "lime",
        "Bran",
        "Car",
    ),
    "lipolytic": (
        "مزو متا پیور A پلاس",
        "مزو متا پیور پلاس",
        "مزو متا پیور",
        "مزو پیور اسلیم پلاس",
        "مزو پیور اسلیم",
        "مزو پلاس",
        "مزو لاغری غبغب",
        "مزو متا",
        "سوپر مزو",
    ),
}


def seed_catalog_titles(apps, schema_editor):
    Item = apps.get_model("core", "TreatmentCatalogItem")
    database = schema_editor.connection.alias
    for category, titles in CATALOG_ITEMS.items():
        for position, title in enumerate(titles, start=1):
            existing = (
                Item.objects.using(database)
                .filter(category=category, name=title, branch__isnull=True)
                .order_by("pk")
                .first()
            )
            if existing is None:
                Item.objects.using(database).create(
                    category=category,
                    name=title,
                    branch_id=None,
                    is_active=True,
                    sort_order=position,
                )
            elif not existing.is_active:
                # The requested titles must be selectable; preserve all
                # other fields if a shared title already exists.
                Item.objects.using(database).filter(pk=existing.pk).update(is_active=True)


class Migration(migrations.Migration):
    dependencies = [("core", "0083_hide_closed_urmia_branch")]
    operations = [
        migrations.RunPython(seed_catalog_titles, migrations.RunPython.noop),
    ]
