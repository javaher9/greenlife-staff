from datetime import timedelta

from django.db import migrations
from django.db.models import Q
from django.utils import timezone


BLOCKED_ALIASES=('پریسا کلکلی','کلکلی','کاملیا','شیما عباسی','عباسی','لاله')
BANAFSHA_ALIASES=('حدیث توانا','توانا','بنفشه','hadis tavana','tavana')
KHORSHIDI_ALIASES=('محمد صالحی','صالحی','خورشیدی','mohammad salehi','khorshidi')


def _norm(value):
    return ' '.join(str(value or '').strip().lower().replace('ي','ی').replace('ك','ک').split())


def _matches(profile, aliases):
    user=profile.user
    identity=_norm(' '.join(filter(None,(user.first_name,user.last_name,user.username))))
    return any(_norm(alias) in identity for alias in aliases)


def rebalance_recent_banafsha_burst(apps, schema_editor):
    EmployeeProfile=apps.get_model('core','EmployeeProfile')
    ReferralLead=apps.get_model('core','ReferralLead')
    Attendance=apps.get_model('core','Attendance')
    CallCenterLeadGroup=apps.get_model('core','CallCenterLeadGroup')

    operators=list(
        EmployeeProfile.objects.filter(
            role='call_center',is_active=True,user__is_active=True
        ).select_related('user').order_by('id')
    )
    banafsha=next((op for op in operators if _matches(op,BANAFSHA_ALIASES)),None)
    if not banafsha:
        return

    day=timezone.localdate()
    present_ids=set(
        Attendance.objects.filter(
            date=day,check_in__isnull=False,check_out__isnull=True,
            user__profile__role='call_center',
            user__profile__is_active=True,user__is_active=True,
        ).values_list('user_id',flat=True)
    )
    candidates=[
        op for op in operators
        if op.user_id in present_ids and not _matches(op,BLOCKED_ALIASES)
    ]
    if len(candidates)<2:
        return

    regular=[op for op in candidates if not _matches(op,KHORSHIDI_ALIASES)]
    khorshidi=next((op for op in candidates if _matches(op,KHORSHIDI_ALIASES)),None)
    if not regular:
        return

    since=timezone.now()-timedelta(hours=24)
    burst=list(
        ReferralLead.objects.filter(
            assigned_to_id=banafsha.id,
            created_at__gte=since,
            status='new',
            country__code='IR',
            first_appointment_by__isnull=True,
        ).filter(
            Q(contact_result='')|Q(contact_result__isnull=True)
        ).order_by('created_at','id')
    )
    if len(burst)<2:
        return

    # Keep already-contacted/appointment leads untouched. Redistribute only the
    # still-new recent burst, evenly across present unrestricted operators.
    sequence=[]
    khorshidi_every=max(1,len(regular)*5)
    for index in range(len(burst)):
        if khorshidi and index and index%khorshidi_every==0:
            sequence.append(khorshidi)
        else:
            sequence.append(regular[index%len(regular)])

    now=timezone.now()
    for lead,operator in zip(burst,sequence):
        if lead.assigned_to_id==operator.id:
            continue
        group_name='شبکه فروش پرسنل'
        notes=_norm(lead.notes)
        source_url=_norm(lead.source_url)
        if 'اینستاگرام - دستی' in notes:
            group_name='اینستاگرام - دستی'
        elif 'تلگرام' in notes or '/telegram/' in source_url:
            group_name='تلگرام - لینک'
        elif '[channel:instagram]' in notes or '[instagram_page:' in notes or '/instagram/' in source_url:
            group_name='اینستاگرام جدید'
        elif '[channel:website]' in notes or 'greenlifeclinics.com' in source_url:
            group_name='ورودی وب‌سایت'

        group,_=CallCenterLeadGroup.objects.get_or_create(
            owner_id=operator.id,name=group_name,
            defaults={'is_default':group_name=='شبکه فروش پرسنل'},
        )
        ReferralLead.objects.filter(pk=lead.pk).update(
            assigned_to_id=operator.id,
            group_id=group.id,
            assigned_at=now,
        )


class Migration(migrations.Migration):
    dependencies=[
        ('core','0072_branch_sms_address'),
    ]

    operations=[
        migrations.RunPython(rebalance_recent_banafsha_burst,migrations.RunPython.noop),
    ]
