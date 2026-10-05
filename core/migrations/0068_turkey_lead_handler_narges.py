from django.db import migrations, models
from django.db.models import Q


def configure_turkey_handler(apps, schema_editor):
    EmployeeProfile=apps.get_model('core','EmployeeProfile')
    ReferralLead=apps.get_model('core','ReferralLead')
    CallCenterLeadGroup=apps.get_model('core','CallCenterLeadGroup')

    candidates=EmployeeProfile.objects.filter(
        role='call_center',
        is_active=True,
        user__is_active=True,
    ).filter(
        Q(user__first_name__icontains='نرگس')
        | (Q(user__first_name__icontains='فاطمه') & Q(user__last_name__icontains='بابایی'))
        | Q(user__username__icontains='narges')
        | Q(user__username__icontains='babaei')
    ).select_related('user')

    handler=candidates.order_by('id').first()
    if not handler:
        return

    EmployeeProfile.objects.filter(handles_turkey_leads=True).exclude(pk=handler.pk).update(handles_turkey_leads=False)
    EmployeeProfile.objects.filter(pk=handler.pk).update(handles_turkey_leads=True)

    group,_=CallCenterLeadGroup.objects.get_or_create(
        owner_id=handler.pk,
        name='Türkiye | Turkey',
        defaults={'is_default':False},
    )
    ReferralLead.objects.filter(
        country__code='TR',
        status__in=('new','contacted','appointment'),
    ).update(
        assigned_to_id=handler.pk,
        group_id=group.pk,
    )


class Migration(migrations.Migration):
    dependencies=[
        ('core','0067_sales_network_permission_and_rad_cleanup'),
    ]

    operations=[
        migrations.AddField(
            model_name='employeeprofile',
            name='handles_turkey_leads',
            field=models.BooleanField(
                default=False,
                help_text='این کاربر مقصد اختصاصی لیدهای Türkiye است.',
            ),
        ),
        migrations.RunPython(configure_turkey_handler,migrations.RunPython.noop),
    ]
