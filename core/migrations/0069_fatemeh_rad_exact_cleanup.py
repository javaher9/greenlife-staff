from django.db import migrations
from django.db.models import Q


def cleanup_fatemeh_rad(apps, schema_editor):
    EmployeeProfile=apps.get_model('core','EmployeeProfile')
    ReferralProfile=apps.get_model('core','ReferralProfile')
    ReferralLead=apps.get_model('core','ReferralLead')
    User=apps.get_model('auth','User')

    rad_profiles=EmployeeProfile.objects.filter(
        Q(user__first_name__icontains='فاطمه راد')
        | Q(user__last_name__icontains='فاطمه راد')
        | (
            (Q(user__first_name__icontains='فاطمه') | Q(user__last_name__icontains='فاطمه'))
            & (Q(user__first_name__icontains='راد') | Q(user__last_name__icontains='راد'))
        )
    )
    user_ids=list(rad_profiles.values_list('user_id',flat=True))
    if not user_ids:
        return

    rad_profiles.update(
        can_use_sales_network=False,
        can_register_instagram_dm_lead=True,
    )

    green_user,_=User.objects.get_or_create(
        username='greenlife-central-source',
        defaults={'first_name':'Green Life','is_active':False},
    )
    green_ref,_=ReferralProfile.objects.get_or_create(
        user_id=green_user.pk,
        defaults={'referral_code':'GLCENTRAL','is_active':False,'created_by_id':None},
    )

    rad_refs=ReferralProfile.objects.filter(user_id__in=user_ids)
    ref_ids=list(rad_refs.values_list('id',flat=True))
    if ref_ids:
        ReferralLead.objects.filter(referrer_id__in=ref_ids).update(referrer_id=green_ref.pk)
        rad_refs.update(is_active=False)


class Migration(migrations.Migration):
    dependencies=[('core','0068_force_rad_cleanup')]
    operations=[
        migrations.RunPython(cleanup_fatemeh_rad,migrations.RunPython.noop),
    ]
