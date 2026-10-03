from django.db import migrations
from django.utils import timezone


NOTICE_TITLE = 'اخطار مدیریت درباره سهم لید'
NOTICE_MESSAGE = (
    'به‌دلیل اینکه تعداد تماس‌های روزانه شما به ۱۰۰ تماس نمی‌رسد، '
    'تا اطلاع ثانوی لیدهای کمتری به شما تعلق می‌گیرد.'
)


def _norm(value):
    return ' '.join(
        str(value or '').strip().lower().replace('ي', 'ی').replace('ك', 'ک').split()
    )


def notify_khorshidi(apps, schema_editor):
    User = apps.get_model('auth', 'User')
    StaffNotification = apps.get_model('core', 'StaffNotification')
    aliases = ('محمد صالحی', 'mohammad salehi', 'mohammad-salehi', 'khorshidi', 'خورشیدی')

    for user in User.objects.filter(is_active=True).iterator():
        identity = _norm(' '.join(
            part for part in (user.first_name, user.last_name, user.username) if part
        ))
        if not any(_norm(alias) in identity for alias in aliases):
            continue
        StaffNotification.objects.get_or_create(
            user=user,
            title=NOTICE_TITLE,
            message=NOTICE_MESSAGE,
            notification_type='lead_allocation_warning',
            defaults={'related_date': timezone.localdate()},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0061_whatsapp_hub'),
    ]

    operations = [
        migrations.RunPython(notify_khorshidi, migrations.RunPython.noop),
    ]
