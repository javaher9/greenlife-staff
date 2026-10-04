from django.db import migrations, models
from django.db.models import Q


def restrict_rad_and_move_leads(apps, schema_editor):
    EmployeeProfile=apps.get_model('core','EmployeeProfile')
    ReferralProfile=apps.get_model('core','ReferralProfile')
    ReferralLead=apps.get_model('core','ReferralLead')
    User=apps.get_model('auth','User')

    rad_profiles=EmployeeProfile.objects.filter(role='admin').filter(
        Q(user__first_name__icontains='راد') | Q(user__last_name__icontains='راد')
    )
    rad_user_ids=list(rad_profiles.values_list('user_id',flat=True))
    if not rad_user_ids:
        return

    rad_profiles.update(
        can_use_sales_network=False,
        can_register_instagram_dm_lead=True,
    )

    green_user, _=User.objects.get_or_create(
        username='greenlife-central-source',
        defaults={'first_name':'Green Life','last_name':'','is_active':False},
    )
    green_ref, _=ReferralProfile.objects.get_or_create(
        user_id=green_user.pk,
        defaults={
            'referral_code':'GLCENTRAL',
            'is_active':False,
            'created_by_id':None,
        },
    )

    rad_ref_ids=list(ReferralProfile.objects.filter(user_id__in=rad_user_ids).values_list('id',flat=True))
    if rad_ref_ids:
        ReferralLead.objects.filter(referrer_id__in=rad_ref_ids).update(referrer_id=green_ref.pk)
        ReferralProfile.objects.filter(id__in=rad_ref_ids).update(is_active=False)


class Migration(migrations.Migration):
    dependencies=[
        ('core','0066_seed_instagram_dm_lead_permissions'),
    ]

    operations=[
        migrations.AddField(
            model_name='employeeprofile',
            name='can_use_sales_network',
            field=models.BooleanField(
                default=True,
                help_text='اجازه دسترسی به شبکه فروش و ثبت لید به نام شبکه شخصی.',
            ),
        ),
        migrations.RunPython(restrict_rad_and_move_leads,migrations.RunPython.noop),
    ]
