from django.db import migrations, models
import django.db.models.deletion


STANDARD_GROUPS = (
    ('شبکه فروش پرسنل', True),
    ('VIP', False),
    ('میزهای قدیمی دکتر جواهریان', False),
    ('وب‌سایت', False),
    ('کمپ', False),
    ('شرکت‌ها و همکاری سازمانی', False),
    ('اینستاگرام', False),
)


def merge_operator_groups(apps, schema_editor):
    Group=apps.get_model('core','CallCenterLeadGroup')
    Lead=apps.get_model('core','ReferralLead')

    canonical={}
    for group in list(Group.objects.order_by('id')):
        clean_name=' '.join((group.name or '').strip().split())
        if not clean_name:
            clean_name=f'گروه {group.pk}'
        existing=canonical.get(clean_name)
        if existing is None:
            group.name=clean_name
            group.owner_id=None
            group.save(update_fields=['name','owner'])
            canonical[clean_name]=group
            continue
        Lead.objects.filter(group_id=group.pk).update(group_id=existing.pk)
        if group.is_default and not existing.is_default:
            existing.is_default=True
            existing.save(update_fields=['is_default'])
        group.delete()

    for name,is_default in STANDARD_GROUPS:
        group,created=Group.objects.get_or_create(
            name=name,defaults={'owner_id':None,'is_default':is_default},
        )
        changed=[]
        if group.owner_id is not None:
            group.owner_id=None
            changed.append('owner')
        if is_default and not group.is_default:
            group.is_default=True
            changed.append('is_default')
        if changed:
            group.save(update_fields=changed)


class Migration(migrations.Migration):

    # Data merge updates ReferralLead foreign keys before constraints change.
    # PostgreSQL must commit those trigger events before ALTER TABLE.
    atomic=False

    dependencies=[
        ('core','0078_network_welcome_password_template'),
    ]

    operations=[
        migrations.AlterField(
            model_name='callcenterleadgroup',
            name='owner',
            field=models.ForeignKey(
                blank=True,null=True,on_delete=django.db.models.deletion.SET_NULL,
                related_name='call_center_lead_groups',to='core.employeeprofile',
                help_text='فیلد قدیمی؛ گروه‌های کال‌سنتر از این پس سراسری هستند.',
            ),
        ),
        migrations.RunPython(merge_operator_groups,migrations.RunPython.noop),
        migrations.RemoveConstraint(
            model_name='callcenterleadgroup',
            name='uniq_cc_group_owner_name',
        ),
        migrations.AddConstraint(
            model_name='callcenterleadgroup',
            constraint=models.UniqueConstraint(fields=('name',),name='uniq_cc_group_name'),
        ),
    ]
