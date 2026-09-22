from django.db import migrations, models
from django.db.models import Count, F
from django.utils import timezone


OPEN_STATUSES = ('new', 'contacted', 'appointment')


def _normalize(value):
    return ' '.join(
        str(value or '').strip().lower().replace('ي', 'ی').replace('ك', 'ک').split()
    )


def _group_name_for(lead):
    notes = _normalize(getattr(lead, 'notes', ''))
    source_url = _normalize(getattr(lead, 'source_url', ''))

    if 'اینستاگرام - دستی' in notes:
        return 'اینستاگرام - دستی'
    if 'تلگرام' in notes or '/telegram/' in source_url:
        return 'تلگرام - لینک'
    if 'بله' in notes or '[channel:bale]' in notes or '/bale/' in source_url:
        return 'بله - لینک'
    if '[channel:instagram]' in notes or '[instagram_page:' in notes or '/instagram/' in source_url:
        return 'اینستاگرام جدید'
    if '[channel:website]' in notes or 'greenlifeclinics.com' in source_url:
        return 'ورودی وب‌سایت'
    if '[channel:crm]' in notes or 'crm' in source_url:
        return 'ورودی CRM'
    if '[channel:whatsapp]' in notes or 'whatsapp' in source_url or 'wa.me' in source_url:
        return 'ورودی واتس‌اپ'
    if '[channel:campaign]' in notes or 'utm_campaign=' in source_url:
        return 'ورودی کمپین'
    return 'شبکه فروش پرسنل'


def backfill_assignment_state(apps, schema_editor):
    ReferralLead = apps.get_model('core', 'ReferralLead')
    EmployeeProfile = apps.get_model('core', 'EmployeeProfile')
    CallCenterLeadGroup = apps.get_model('core', 'CallCenterLeadGroup')

    # Existing ownership gets a sensible assignment timestamp so the new
    # equal-routing counter starts with the data already visible in production.
    ReferralLead.objects.filter(
        assigned_to__isnull=False,
        assigned_at__isnull=True,
    ).update(assigned_at=F('created_at'))

    operators = list(
        EmployeeProfile.objects.filter(
            role='call_center',
            is_active=True,
            user__is_active=True,
        ).order_by('id')
    )
    if not operators:
        return

    today = timezone.localdate()
    rows = (
        ReferralLead.objects
        .filter(
            assigned_to_id__in=[op.id for op in operators],
            assigned_at__date=today,
        )
        .values('assigned_to_id')
        .annotate(count=Count('id'))
    )
    counts = {op.id: 0 for op in operators}
    for row in rows:
        counts[row['assigned_to_id']] = row['count']

    now = timezone.now()
    pending = ReferralLead.objects.filter(
        assigned_to__isnull=True,
        status__in=OPEN_STATUSES,
    ).order_by('created_at', 'id')

    for lead in pending.iterator():
        operator = min(operators, key=lambda op: (counts[op.id], op.id))
        group_name = _group_name_for(lead)
        group, _ = CallCenterLeadGroup.objects.get_or_create(
            owner_id=operator.id,
            name=group_name,
            defaults={'is_default': group_name == 'شبکه فروش پرسنل'},
        )
        lead.assigned_to_id = operator.id
        lead.group_id = group.id
        lead.assigned_at = now
        lead.updated_at = now
        lead.save(update_fields=['assigned_to', 'group', 'assigned_at', 'updated_at'])
        counts[operator.id] += 1


class Migration(migrations.Migration):
    dependencies = [
        ('core', '0045_website_lead_integration_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='referrallead',
            name='assigned_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        migrations.RunPython(backfill_assignment_state, migrations.RunPython.noop),
    ]
