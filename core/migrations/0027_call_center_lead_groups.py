from django.db import migrations, models
import django.db.models.deletion


STARTER_GROUPS = (
    ('شبکه فروش پرسنل', True),
    ('وب‌سایت', False),
    ('کمپ', False),
    ('شرکت‌ها و همکاری سازمانی', False),
    ('اینستاگرام', False),
)


def seed_call_center_groups(apps, schema_editor):
    EmployeeProfile=apps.get_model('core','EmployeeProfile')
    CallCenterLeadGroup=apps.get_model('core','CallCenterLeadGroup')
    ReferralLead=apps.get_model('core','ReferralLead')

    for operator in EmployeeProfile.objects.filter(role='call_center',is_active=True):
        default_group=None
        for name,is_default in STARTER_GROUPS:
            group,_=CallCenterLeadGroup.objects.get_or_create(
                owner=operator,name=name,defaults={'is_default':is_default},
            )
            if is_default:
                default_group=group
                if not group.is_default:
                    group.is_default=True
                    group.save(update_fields=['is_default'])
        if default_group:
            ReferralLead.objects.filter(
                assigned_to=operator,group__isnull=True
            ).update(group=default_group)


class Migration(migrations.Migration):
    dependencies=[('core','0026_receptionist_role')]

    operations=[
        migrations.CreateModel(
            name='CallCenterLeadGroup',
            fields=[
                ('id',models.BigAutoField(auto_created=True,primary_key=True,serialize=False,verbose_name='ID')),
                ('name',models.CharField(max_length=80)),
                ('is_default',models.BooleanField(default=False)),
                ('created_at',models.DateTimeField(auto_now_add=True)),
                ('owner',models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,related_name='call_center_lead_groups',to='core.employeeprofile')),
            ],
            options={'ordering':['-is_default','name','id']},
        ),
        migrations.AddConstraint(
            model_name='callcenterleadgroup',
            constraint=models.UniqueConstraint(fields=('owner','name'),name='uniq_cc_group_owner_name'),
        ),
        migrations.AddField(
            model_name='referrallead',
            name='group',
            field=models.ForeignKey(blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,related_name='leads',to='core.callcenterleadgroup'),
        ),
        migrations.RunPython(seed_call_center_groups,migrations.RunPython.noop),
    ]
